<?php
declare(strict_types=1);

namespace MaruVend\Vend;

use MaruVend\Audit\AuditLog;
use MaruVend\Db;
use MaruVend\Float\FloatLedger;
use MaruVend\Float\InsufficientFloat;
use MaruVend\Provider\ProviderResult;
use MaruVend\Provider\VendProvider;
use MaruVend\Queue\RateLimiter;
use MaruVend\Settings;
use MaruVend\Support\Ulid;
use PDO;

/**
 * The vend core: sale creation, state transitions, float movements and outcome handling.
 * Channels call quote/accept/markPaid; only the queue worker calls processVend/processAdvice,
 * so no channel request ever reaches BPC directly (clause 7.6).
 */
final class VendService
{
    private FloatLedger $float;

    public function __construct(
        private PDO $pdo,
        private Settings $settings,
        private VendProvider $provider,
        private AuditLog $audit,
        private ?RateLimiter $limiter = null,
    ) {
        $this->float = new FloatLedger($pdo);
    }

    // ------------------------------------------------------------------ channel-facing

    /**
     * Step 1: validate the meter with BPC and create the sale as QUOTED.
     * Idempotent per (merchant, idempotency key): a repeated request returns the same sale.
     */
    public function quote(array $channel, string $meter, int $amountThebe, string $idempotencyKey): array
    {
        if ($existing = $this->findByIdempotency((int) $channel['merchant_id'], $idempotencyKey)) {
            return $existing;
        }
        $this->validateRequest($channel, $meter, $amountThebe);

        $clientSaleId = Ulid::generate();
        $this->limiter?->acquire();
        $r = $this->provider->confirmCustomer($clientSaleId . 'Q', $meter, $amountThebe, $channel['type']);
        if (!$r->ok()) {
            throw match ($r->outcome) {
                ProviderResult::BUSINESS_FAULT => new VendException('METER_REJECTED', $r->message ?: 'Meter could not be confirmed by BPC.'),
                default => new VendException('BPC_UNAVAILABLE', 'BPC could not be reached. Please try again.', 503),
            };
        }

        return Db::tx($this->pdo, function () use ($channel, $meter, $amountThebe, $idempotencyKey, $clientSaleId, $r) {
            $this->pdo->exec('INSERT INTO receipt_seq () VALUES ()');
            $seq = (string) $this->pdo->lastInsertId(); // read before any other statement resets it
            $receiptNo = $this->settings->get('receipt_prefix') . str_pad($seq, 10, '0', STR_PAD_LEFT);
            $ttl = $this->settings->int('quote_ttl_s');
            $this->pdo->prepare(
                'INSERT INTO vend_sales (merchant_id, channel_id, idempotency_key, receipt_no, client_sale_id, meter_number,
                     customer_name, amount_thebe, state, provider, quote_expires_at)
                 VALUES (?,?,?,?,?,?,?,?,?,?, NOW(6) + INTERVAL ? SECOND)'
            )->execute([$channel['merchant_id'], $channel['id'], $idempotencyKey, $receiptNo, $clientSaleId, $meter,
                $r->data['customerName'] ?? null, $amountThebe, SaleState::QUOTED, $this->provider->name(), $ttl]);
            $saleId = (int) $this->pdo->lastInsertId();
            $this->event($saleId, null, SaleState::QUOTED, 'Meter confirmed by BPC', "channel:{$channel['id']}");
            return $this->sale($saleId);
        });
    }

    /** Step 2: customer accepted name and meter. POS sales go straight to the queue. */
    public function accept(array $channel, int $saleId): array
    {
        return Db::tx($this->pdo, function () use ($channel, $saleId) {
            $sale = $this->lockSale($saleId, $channel);
            if ($sale['state'] !== SaleState::QUOTED) {
                return $sale; // idempotent
            }
            if ($this->expired($sale)) {
                $this->transition($sale, SaleState::EXPIRED, 'Quote expired before acceptance', 'system');
                throw new VendException('QUOTE_EXPIRED', SaleState::customerMessage(SaleState::EXPIRED));
            }
            if ($channel['type'] === 'POS') {
                $this->reserveAndQueue($sale, "channel:{$channel['id']}", 'Accepted at POS; paid from merchant float');
            } else {
                $this->transition($sale, SaleState::PAYMENT_PENDING, 'Customer accepted; awaiting payment', "channel:{$channel['id']}");
            }
            return $this->sale($saleId);
        });
    }

    /** Step 3 (app/web/USSD): the payment provider confirmed the customer paid. */
    public function markPaid(array $channel, int $saleId, string $paymentRef): array
    {
        return Db::tx($this->pdo, function () use ($channel, $saleId, $paymentRef) {
            $sale = $this->lockSale($saleId, $channel);
            if ($sale['state'] !== SaleState::PAYMENT_PENDING) {
                return $sale;
            }
            $this->reserveAndQueue($sale, "channel:{$channel['id']}", "Payment received ref $paymentRef");
            return $this->sale($saleId);
        });
    }

    public function status(array $channel, int $saleId): array
    {
        $sale = $this->sale($saleId);
        if ((int) $sale['merchant_id'] !== (int) $channel['merchant_id']) {
            throw new VendException('NOT_FOUND', 'Sale not found', 404);
        }
        return $sale;
    }

    /** Free reprint by receipt number or by meter (latest successful sale). */
    public function reprint(?string $receiptNo, ?string $meter): ?array
    {
        if ($receiptNo) {
            $st = $this->pdo->prepare("SELECT id FROM vend_sales WHERE receipt_no = ? AND state = 'SUCCEEDED'");
            $st->execute([$receiptNo]);
        } else {
            $st = $this->pdo->prepare("SELECT id FROM vend_sales WHERE meter_number = ? AND state = 'SUCCEEDED' ORDER BY id DESC LIMIT 1");
            $st->execute([$meter]);
        }
        $id = $st->fetchColumn();
        return $id ? $this->sale((int) $id) : null;
    }

    /** Sale with receipt fields (Annexure 1) when a token exists. */
    public function sale(int $saleId): array
    {
        $st = $this->pdo->prepare('SELECT s.*, t.token, t.key_change_1, t.key_change_2, t.kwh, t.unit_rate_thebe, t.cost_units_thebe,
                t.fixed_charge_thebe, t.gov_levy_thebe, t.vat_thebe, t.tariff_index, t.total_thebe, t.issued_at
            FROM vend_sales s LEFT JOIN vend_tokens t ON t.sale_id = s.id WHERE s.id = ?');
        $st->execute([$saleId]);
        $s = $st->fetch();
        if (!$s) {
            throw new VendException('NOT_FOUND', 'Sale not found', 404);
        }
        $s['message'] = SaleState::customerMessage($s['state']);
        return $s;
    }

    // ------------------------------------------------------------------ worker-facing

    /** Submit the credit vend for a RESERVED sale. Called only by the queue worker. */
    public function processVend(int $saleId): void
    {
        $sale = Db::tx($this->pdo, function () use ($saleId) {
            $sale = $this->lockSale($saleId);
            if ($sale['state'] === SaleState::SUBMITTED) {
                // A previous worker died after sending: never send again, recover the outcome instead.
                $this->transition($sale, SaleState::UNKNOWN, 'Worker interrupted after submission; recovering outcome', 'worker');
                $this->scheduleAdvice($saleId, 0);
                return null;
            }
            if ($sale['state'] !== SaleState::RESERVED) {
                $this->finishJobs($saleId);
                return null;
            }
            $this->transition($sale, SaleState::SUBMITTED, 'Submitted to BPC', 'worker');
            $this->pdo->prepare('UPDATE vend_sales SET attempts = attempts + 1, submitted_at = COALESCE(submitted_at, NOW(6)) WHERE id = ?')->execute([$saleId]);
            return $this->sale($saleId);
        });
        if (!$sale) {
            return;
        }

        $this->limiter?->acquire();
        $r = $this->provider->creditVend($sale['client_sale_id'], $sale['meter_number'], (int) $sale['amount_thebe'], $this->terminal($sale));
        $this->logExchange($saleId, 'creditvend', $r);

        Db::tx($this->pdo, function () use ($saleId, $r) {
            $sale = $this->lockSale($saleId);
            switch ($r->outcome) {
                case ProviderResult::OK:
                    $this->succeed($sale, $r, 'Token issued by BPC');
                    break;
                case ProviderResult::BUSINESS_FAULT:
                    $this->fail($sale, 'BPC refused: ' . ($r->message ?? 'fault'), $r->faultCode);
                    break;
                case ProviderResult::SYSTEM_FAULT:
                    if ((int) $sale['attempts'] >= 5) {
                        $this->fail($sale, 'Not processed by BPC after 5 attempts: ' . ($r->message ?? ''), $r->faultCode);
                    } else {
                        $this->transition($sale, SaleState::RESERVED, 'Not processed by BPC (' . ($r->message ?? 'system fault') . '); will retry', 'worker', $r->faultCode);
                        $this->pdo->prepare('UPDATE queue_jobs SET next_run_at = NOW(6) + INTERVAL ? SECOND, locked_by = NULL WHERE sale_id = ? AND done = 0')
                            ->execute([min(60, 5 * (int) $sale['attempts']), $saleId]);
                    }
                    break;
                default: // UNKNOWN, DUPLICATE, PENDING: outcome uncertain, never re-vend
                    $this->transition($sale, SaleState::UNKNOWN, 'Outcome uncertain (' . ($r->message ?? $r->outcome) . '); recovering with last response', 'worker', $r->faultCode);
                    $delay = $r->outcome === ProviderResult::DUPLICATE ? 0 : $this->settings->int('advice_first_delay_s');
                    $this->scheduleAdvice($saleId, $delay);
            }
        });
    }

    /** Recover the outcome of an UNKNOWN sale with last response. Called only by the queue worker. */
    public function processAdvice(int $saleId): void
    {
        $sale = $this->sale($saleId);
        if (!in_array($sale['state'], SaleState::UNRESOLVED, true)) {
            Db::tx($this->pdo, fn () => $this->finishJobs($saleId));
            return;
        }
        $this->limiter?->acquire();
        $r = $this->provider->lastResponse($sale['client_sale_id']);
        $this->logExchange($saleId, 'lastresponse', $r);

        Db::tx($this->pdo, function () use ($saleId, $r) {
            $sale = $this->lockSale($saleId);
            if (!in_array($sale['state'], SaleState::UNRESOLVED, true)) {
                $this->finishJobs($saleId);
                return;
            }
            switch ($r->outcome) {
                case ProviderResult::OK:
                    $this->succeed($sale, $r, 'Token recovered by last response');
                    return;
                case ProviderResult::BUSINESS_FAULT:
                    $this->fail($sale, 'BPC confirmed failure: ' . ($r->message ?? ''), $r->faultCode);
                    return;
                case ProviderResult::NOT_FOUND:
                    $this->fail($sale, 'BPC has no record of the sale; it was never processed', $r->faultCode);
                    return;
            }
            // Still pending: retry until the advice window closes, then hold for manual reconciliation.
            $age = time() - strtotime((string) $sale['submitted_at']);
            if ($sale['state'] === SaleState::UNKNOWN && $age >= $this->settings->int('advice_window_s')) {
                $this->transition($sale, SaleState::MANUAL_REVIEW, 'Unresolved after advice window; held for reconciliation with BPC', 'worker', $r->faultCode);
                $this->scheduleAdvice($saleId, 600);
                return;
            }
            $this->scheduleAdvice($saleId, $r->retryAfterS ?? $this->settings->int('advice_interval_s'));
        });
    }

    /** Expire quotes and unpaid sales past their deadline. */
    public function expireStale(): int
    {
        $ids = $this->pdo->query("SELECT id FROM vend_sales WHERE state IN ('QUOTED','PAYMENT_PENDING') AND quote_expires_at < NOW(6)")->fetchAll(PDO::FETCH_COLUMN);
        foreach ($ids as $id) {
            Db::tx($this->pdo, function () use ($id) {
                $sale = $this->lockSale((int) $id);
                if (in_array($sale['state'], [SaleState::QUOTED, SaleState::PAYMENT_PENDING], true)) {
                    $this->transition($sale, SaleState::EXPIRED, 'Expired before payment', 'sweeper');
                }
            });
        }
        return count($ids);
    }

    /** Admin resolution of a MANUAL_REVIEW sale after reconciliation with BPC records (two-person approved). */
    public function resolveManually(int $saleId, bool $tokenIssued, array $tokenData, string $actor): void
    {
        Db::tx($this->pdo, function () use ($saleId, $tokenIssued, $tokenData, $actor) {
            $sale = $this->lockSale($saleId);
            if ($sale['state'] !== SaleState::MANUAL_REVIEW) {
                throw new VendException('BAD_STATE', 'Sale is not awaiting manual review');
            }
            $tokenIssued
                ? $this->succeed($sale, new ProviderResult(ProviderResult::OK, $tokenData), "Resolved manually by $actor from BPC records")
                : $this->fail($sale, "Resolved manually by $actor: BPC records show no token");
        });
    }

    // ------------------------------------------------------------------ internals

    private function validateRequest(array $channel, string $meter, int $amount): void
    {
        if (!preg_match('/^\d{11,13}$/', $meter)) {
            throw new VendException('BAD_METER', 'Meter number must be 11 to 13 digits.');
        }
        $min = $this->settings->int('min_amount_thebe');
        $max = $this->settings->int('max_amount_thebe');
        if ($amount < $min || $amount > $max) {
            throw new VendException('BAD_AMOUNT', sprintf('Amount must be between P%.2f and P%.2f.', $min / 100, $max / 100));
        }
        $m = $this->pdo->prepare('SELECT * FROM merchants WHERE id = ?');
        $m->execute([$channel['merchant_id']]);
        $merchant = $m->fetch();
        if (!$merchant || !$merchant['active'] || $merchant['kyc_status'] !== 'verified') {
            throw new VendException('MERCHANT_INACTIVE', 'Merchant is not active.', 403);
        }
        if ((int) $merchant['value_limit'] > 0 && $amount > (int) $merchant['value_limit']) {
            throw new VendException('MERCHANT_LIMIT', 'Amount exceeds this outlet\'s limit.');
        }
        if ((int) $merchant['daily_limit'] > 0) {
            $d = $this->pdo->prepare("SELECT COALESCE(SUM(amount_thebe),0) FROM vend_sales WHERE merchant_id = ?
                AND created_at >= CURDATE() AND state NOT IN ('FAILED','EXPIRED')");
            $d->execute([$merchant['id']]);
            if ((int) $d->fetchColumn() + $amount > (int) $merchant['daily_limit']) {
                throw new VendException('MERCHANT_DAILY_LIMIT', 'This outlet has reached its daily limit.');
            }
        }
    }

    private function reserveAndQueue(array $sale, string $actor, string $cause): void
    {
        // Cap the money that can sit in unresolved sales, so a BPC outage cannot drain the float.
        $unresolved = (int) $this->pdo->query("SELECT COALESCE(SUM(amount_thebe),0) FROM vend_sales WHERE state IN ('UNKNOWN','MANUAL_REVIEW')")->fetchColumn();
        if ($unresolved + (int) $sale['amount_thebe'] > $this->settings->int('max_unknown_thebe')) {
            throw new VendException('VENDING_PAUSED', 'Vending is paused while BPC confirms earlier sales. Please try again shortly.', 503);
        }
        try {
            $this->float->reserve((int) $sale['id'], (int) $sale['amount_thebe']);
        } catch (InsufficientFloat $e) {
            throw new VendException('FLOAT_EXHAUSTED', 'Electricity sales are temporarily unavailable.', 503);
        }
        $this->transition($sale, SaleState::RESERVED, $cause . '; amount held against float', $actor);
        $this->pdo->prepare("INSERT INTO queue_jobs (sale_id, action) VALUES (?, 'vend')")->execute([$sale['id']]);
    }

    private function succeed(array $sale, ProviderResult $r, string $cause): void
    {
        $d = $r->data;
        $this->pdo->prepare('INSERT INTO vend_tokens (sale_id, token, key_change_1, key_change_2, kwh, unit_rate_thebe, cost_units_thebe,
                fixed_charge_thebe, gov_levy_thebe, vat_thebe, tariff_index, total_thebe) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)')
            ->execute([$sale['id'], $d['token'], $d['keyChange1'] ?? null, $d['keyChange2'] ?? null, $d['kwh'] ?? 0,
                $d['unitRateThebe'] ?? null, $d['costUnitsThebe'] ?? 0, $d['fixedChargeThebe'] ?? 0, $d['govLevyThebe'] ?? 0,
                $d['vatThebe'] ?? 0, $d['tariffIndex'] ?? null, $d['totalThebe'] ?: $sale['amount_thebe']]);
        $this->pdo->prepare('UPDATE vend_sales SET provider_ref = ?, customer_name = COALESCE(?, customer_name), resolved_at = NOW(6) WHERE id = ?')
            ->execute([$d['providerRef'] ?? null, $d['customerName'] ?? null, $sale['id']]);
        $this->float->settle((int) $sale['id'], (int) $sale['amount_thebe']);
        $fee = intdiv((int) $sale['amount_thebe'] * $this->settings->int('service_fee_bp'), 10000);
        $this->float->fee((int) $sale['id'], $fee);
        $this->transition($sale, SaleState::SUCCEEDED, $cause, 'worker');
        $this->finishJobs((int) $sale['id']);
    }

    private function fail(array $sale, string $cause, ?string $faultCode = null): void
    {
        $this->float->release((int) $sale['id'], (int) $sale['amount_thebe']);
        $this->pdo->prepare('UPDATE vend_sales SET resolved_at = NOW(6) WHERE id = ?')->execute([$sale['id']]);
        $this->transition($sale, SaleState::FAILED, $cause . '; float released', 'worker', $faultCode);
        $this->finishJobs((int) $sale['id']);
    }

    private function scheduleAdvice(int $saleId, int $delayS): void
    {
        $this->pdo->prepare("UPDATE queue_jobs SET action = 'advice', next_run_at = NOW(6) + INTERVAL ? SECOND, locked_by = NULL, locked_at = NULL,
                attempts = attempts + 1 WHERE sale_id = ? AND done = 0")->execute([$delayS, $saleId]);
    }

    private function finishJobs(int $saleId): void
    {
        $this->pdo->prepare('UPDATE queue_jobs SET done = 1, locked_by = NULL WHERE sale_id = ?')->execute([$saleId]);
    }

    private function transition(array $sale, string $to, string $cause, string $actor, ?string $faultCode = null): void
    {
        if (!SaleState::allowed($sale['state'], $to)) {
            throw new \LogicException("Illegal transition {$sale['state']} -> $to for sale {$sale['id']}");
        }
        $this->pdo->prepare('UPDATE vend_sales SET state = ?, fault_code = COALESCE(?, fault_code) WHERE id = ?')->execute([$to, $faultCode, $sale['id']]);
        $this->event((int) $sale['id'], $sale['state'], $to, $cause, $actor, $faultCode);
    }

    private function event(int $saleId, ?string $from, string $to, string $cause, string $actor, ?string $faultCode = null): void
    {
        $seq = $this->pdo->prepare('SELECT COALESCE(MAX(seq),0) + 1 FROM sale_events WHERE sale_id = ?');
        $seq->execute([$saleId]);
        $this->pdo->prepare('INSERT INTO sale_events (sale_id, seq, from_state, to_state, cause, fault_code, actor) VALUES (?,?,?,?,?,?,?)')
            ->execute([$saleId, (int) $seq->fetchColumn(), $from, $to, mb_substr($cause, 0, 255), $faultCode, $actor]);
        $this->audit->record($actor, 'system', 'sale.' . strtolower($to), 'vend_sales', (string) $saleId, $from, $to);
    }

    private function lockSale(int $saleId, ?array $channel = null): array
    {
        $st = $this->pdo->prepare('SELECT * FROM vend_sales WHERE id = ? FOR UPDATE');
        $st->execute([$saleId]);
        $sale = $st->fetch();
        if (!$sale || ($channel && (int) $sale['merchant_id'] !== (int) $channel['merchant_id'])) {
            throw new VendException('NOT_FOUND', 'Sale not found', 404);
        }
        return $sale;
    }

    private function expired(array $sale): bool
    {
        return $sale['quote_expires_at'] !== null && strtotime((string) $sale['quote_expires_at']) < time();
    }

    private function findByIdempotency(int $merchantId, string $key): ?array
    {
        $st = $this->pdo->prepare('SELECT id FROM vend_sales WHERE merchant_id = ? AND idempotency_key = ?');
        $st->execute([$merchantId, $key]);
        $id = $st->fetchColumn();
        return $id ? $this->sale((int) $id) : null;
    }

    private function terminal(array $sale): string
    {
        $st = $this->pdo->prepare('SELECT type FROM channels WHERE id = ?');
        $st->execute([$sale['channel_id']]);
        return (string) $st->fetchColumn();
    }

    private function logExchange(int $saleId, string $op, ProviderResult $r): void
    {
        if (!$r->exchange) {
            return;
        }
        // Mask tokens in stored traffic: they are kept in vend_tokens only.
        $mask = fn (string $s) => preg_replace('/("(?:stsCipher|keychangetoken[12])"\s*:\s*")(\d{4})\d+(\d{4})"/', '$1$2************$3"', $s);
        $ins = $this->pdo->prepare('INSERT INTO vend_messages (sale_id, operation, direction, http_status, body, body_sha256) VALUES (?,?,?,?,?,?)');
        $req = (string) ($r->exchange['request'] ?? '');
        $resp = (string) ($r->exchange['response'] ?? '');
        $ins->execute([$saleId, $op, 'req', null, $req, hash('sha256', $req)]);
        $ins->execute([$saleId, $op, 'resp', $r->exchange['http'] ?? null, $mask($resp), hash('sha256', $resp)]);
    }
}
