<?php
declare(strict_types=1);

namespace MaruVend\Tests;

use MaruVend\Provider\ProviderResult;
use MaruVend\Vend\VendException;

final class VendFlowTest extends TestCase
{
    public function testPosSaleIssuesTokenSettlesFloatAndAccruesFee(): void
    {
        $s = $this->posSale(2500);
        $this->assertSame('RESERVED', $s['state']);
        $this->assertSame(['available' => 997_500, 'reserved' => 2500, 'last_deposit_thebe' => 1_000_000], $this->float());

        $this->vend->processVend((int) $s['id']);
        $s = $this->vend->sale((int) $s['id']);

        $this->assertSame('SUCCEEDED', $s['state']);
        $this->assertSame('12345678901234567890', $s['token']);
        $this->assertSame(['QUOTED', 'RESERVED', 'SUBMITTED', 'SUCCEEDED'], $this->states((int) $s['id']));
        $this->assertSame(['available' => 997_500, 'reserved' => 0, 'last_deposit_thebe' => 1_000_000], $this->float());
        $fee = $this->pdo->query("SELECT amount_thebe FROM float_ledger WHERE entry_type = 'fee'")->fetchColumn();
        $this->assertSame(125, (int) $fee); // 5% of P25.00
    }

    public function testRestartedWorkerReleasesOnlyItsOwnStaleLocks(): void
    {
        $a = $this->posSale(1000);
        $b = $this->posSale(1000);
        // w1 crashed holding $a's job; w2 is alive and holds $b's.
        $this->pdo->prepare("UPDATE queue_jobs SET locked_by = 'w1', locked_at = NOW(6) WHERE sale_id = ?")->execute([$a['id']]);
        $this->pdo->prepare("UPDATE queue_jobs SET locked_by = 'w2', locked_at = NOW(6) WHERE sale_id = ?")->execute([$b['id']]);
        $w1 = new \MaruVend\Queue\Worker($this->pdo, $this->app->settings, $this->vend, 'w1');
        $this->assertSame(1, $w1->releaseOwnLocks());
        $locks = $this->pdo->query('SELECT sale_id, locked_by FROM queue_jobs ORDER BY sale_id')->fetchAll(\PDO::FETCH_KEY_PAIR);
        $this->assertNull($locks[$a['id']], 'own stale lock released at once');
        $this->assertSame('w2', $locks[$b['id']], "another worker's lock untouched");
    }

    public function testWebSaleWaitsForPaymentBeforeQueueing(): void
    {
        $s = $this->vend->quote($this->web, '94949494949', 3000, 'w1');
        $s = $this->vend->accept($this->web, (int) $s['id']);
        $this->assertSame('PAYMENT_PENDING', $s['state']);
        $this->assertSame(0, (int) $this->pdo->query('SELECT COUNT(*) FROM queue_jobs')->fetchColumn());
        $s = $this->vend->markPaid($this->web, (int) $s['id'], 'PAY1');
        $this->assertSame('RESERVED', $s['state']);
        $this->assertSame(1, (int) $this->pdo->query('SELECT COUNT(*) FROM queue_jobs')->fetchColumn());
    }

    public function testSameIdempotencyKeyReturnsSameSaleAndNeverDoubleCharges(): void
    {
        $a = $this->vend->quote($this->pos, '94949494949', 2500, 'same-key');
        $b = $this->vend->quote($this->pos, '94949494949', 2500, 'same-key');
        $this->assertSame($a['id'], $b['id']);
        $this->vend->accept($this->pos, (int) $a['id']);
        $this->vend->accept($this->pos, (int) $a['id']);
        $this->assertSame(2500, $this->float()['reserved']);
    }

    public function testBusinessFaultFailsSaleAndReleasesFloat(): void
    {
        $this->provider->vendQueue[] = new ProviderResult(ProviderResult::BUSINESS_FAULT, [], '108', 'Meter blocked');
        $s = $this->posSale(2500);
        $this->vend->processVend((int) $s['id']);
        $s = $this->vend->sale((int) $s['id']);
        $this->assertSame('FAILED', $s['state']);
        $this->assertSame('108', $s['fault_code']);
        $this->assertSame(1_000_000, $this->float()['available']);
        $this->assertSame(0, $this->float()['reserved']);
    }

    public function testUncertainOutcomeIsNeverReVendedAndIsRecoveredByLastResponse(): void
    {
        $this->provider->vendQueue[] = new ProviderResult(ProviderResult::UNKNOWN, [], 'CURL28', 'No response within timeout');
        $s = $this->posSale(2500);
        $this->vend->processVend((int) $s['id']);
        $this->assertSame('UNKNOWN', $this->vend->sale((int) $s['id'])['state']);
        $this->assertSame(2500, $this->float()['reserved'], 'money stays held while outcome unknown');

        // Worker runs the vend job again (e.g. after a crash): must NOT call creditVend again.
        $this->vend->processVend((int) $s['id']);
        $this->assertSame(1, $this->provider->vendCalls());

        $this->provider->adviceQueue[] = new ProviderResult(ProviderResult::PENDING, [], '133');
        $this->vend->processAdvice((int) $s['id']);
        $this->assertSame('UNKNOWN', $this->vend->sale((int) $s['id'])['state']);

        $this->provider->adviceQueue[] = FakeProvider::token('99998888777766665555');
        $this->vend->processAdvice((int) $s['id']);
        $s = $this->vend->sale((int) $s['id']);
        $this->assertSame('SUCCEEDED', $s['state']);
        $this->assertSame('99998888777766665555', $s['token']);
        $this->assertSame(1, $this->provider->vendCalls());
        $this->assertSame(0, $this->float()['reserved']);
    }

    public function testLastResponseFailureReleasesFloat(): void
    {
        $this->provider->vendQueue[] = new ProviderResult(ProviderResult::UNKNOWN);
        $s = $this->posSale(2500);
        $this->vend->processVend((int) $s['id']);
        $this->provider->adviceQueue[] = new ProviderResult(ProviderResult::NOT_FOUND, [], '209');
        $this->vend->processAdvice((int) $s['id']);
        $this->assertSame('FAILED', $this->vend->sale((int) $s['id'])['state']);
        $this->assertSame(1_000_000, $this->float()['available']);
    }

    public function testUnresolvedAfterWindowGoesToManualReviewAndKeepsMoneyHeld(): void
    {
        $this->app->settings->apply('advice_window_s', '1', 'test', $this->app->audit);
        $this->provider->vendQueue[] = new ProviderResult(ProviderResult::UNKNOWN);
        $s = $this->posSale(2500);
        $this->vend->processVend((int) $s['id']);
        $this->pdo->exec('UPDATE vend_sales SET submitted_at = NOW(6) - INTERVAL 10 SECOND');
        $this->vend->processAdvice((int) $s['id']);
        $this->assertSame('MANUAL_REVIEW', $this->vend->sale((int) $s['id'])['state']);
        $this->assertSame(2500, $this->float()['reserved']);
    }

    public function testDuplicateIsTreatedAsUnknownAndRecovered(): void
    {
        $this->provider->vendQueue[] = new ProviderResult(ProviderResult::DUPLICATE, [], '09');
        $s = $this->posSale();
        $this->vend->processVend((int) $s['id']);
        $this->assertSame('UNKNOWN', $this->vend->sale((int) $s['id'])['state']);
        $job = $this->pdo->query('SELECT action FROM queue_jobs')->fetchColumn();
        $this->assertSame('advice', $job);
    }

    public function testSystemFaultRetriesWithSameClientSaleId(): void
    {
        $this->provider->vendQueue[] = new ProviderResult(ProviderResult::SYSTEM_FAULT, [], 'CURL7', 'Connection refused');
        $s = $this->posSale();
        $this->vend->processVend((int) $s['id']);
        $this->assertSame('RESERVED', $this->vend->sale((int) $s['id'])['state']);
        $this->vend->processVend((int) $s['id']);
        $this->assertSame('SUCCEEDED', $this->vend->sale((int) $s['id'])['state']);
        $ids = array_column(array_filter($this->provider->calls, fn ($c) => $c[0] === 'vend'), 1);
        $this->assertCount(2, $ids);
        $this->assertSame($ids[0], $ids[1], 'retry must reuse the same clientSaleId');
    }

    public function testFloatCannotGoNegative(): void
    {
        $this->expectException(VendException::class);
        $this->expectExceptionMessage('temporarily unavailable');
        $this->app->settings->apply('max_amount_thebe', '2000000', 'test', $this->app->audit);
        $this->posSale(1_000_001);
    }

    public function testUnresolvedCapPausesVending(): void
    {
        $this->app->settings->apply('max_unknown_thebe', '3000', 'test', $this->app->audit);
        $this->provider->vendQueue[] = new ProviderResult(ProviderResult::UNKNOWN);
        $s = $this->posSale(2500);
        $this->vend->processVend((int) $s['id']);
        try {
            $this->posSale(1000);
            $this->fail('expected vending to pause');
        } catch (VendException $e) {
            $this->assertSame('VENDING_PAUSED', $e->errorCode);
        }
    }

    public function testValidation(): void
    {
        foreach ([['123', 2500, 'BAD_METER'], ['94949494949', 500, 'BAD_AMOUNT'], ['07070707070', 2500, 'METER_REJECTED']] as [$m, $a, $code]) {
            try {
                $this->vend->quote($this->pos, $m, $a, 'v' . $code);
                $this->fail("expected $code");
            } catch (VendException $e) {
                $this->assertSame($code, $e->errorCode);
            }
        }
    }

    public function testQuoteExpires(): void
    {
        $s = $this->vend->quote($this->pos, '94949494949', 2500, 'exp');
        $this->pdo->exec('UPDATE vend_sales SET quote_expires_at = NOW(6) - INTERVAL 1 SECOND');
        $this->assertSame(1, $this->vend->expireStale());
        $this->assertSame('EXPIRED', $this->vend->sale((int) $s['id'])['state']);
    }

    public function testIllegalTransitionsAreImpossible(): void
    {
        $s = $this->posSale();
        $this->vend->processVend((int) $s['id']);
        $this->vend->processVend((int) $s['id']); // already succeeded: no-op, no second token
        $this->assertSame(1, $this->provider->vendCalls());
        $this->assertSame(1, (int) $this->pdo->query("SELECT COUNT(*) FROM float_ledger WHERE entry_type='settle'")->fetchColumn());
    }

    public function testConfirmedNotProcessedFromProviderFailsAtOnce(): void
    {
        $this->provider->vendQueue[] = new ProviderResult(ProviderResult::NOT_FOUND, [], 'LastResponseEx', 'not processed');
        $s = $this->posSale();
        $this->vend->processVend((int) $s['id']);
        $this->assertSame('FAILED', $this->vend->sale((int) $s['id'])['state']);
        $this->assertSame(0, $this->float()['reserved']);
    }
}
