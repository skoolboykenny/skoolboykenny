<?php
declare(strict_types=1);

namespace MaruVend\Channels;

/**
 * USSD menu for basic phones. Works with the common aggregator callback format: each request
 * carries sessionId, phoneNumber and `text` (all inputs so far joined by "*"); the reply starts
 * with "CON " (menu continues) or "END " (session closes).
 *
 * The session never waits for BPC: after the customer approves payment the session ends with
 * "token will be sent by SMS", so USSD session timeouts can never interrupt a sale.
 *
 *   1 Buy electricity -> meter -> amount -> confirm name -> payment method -> END (token by SMS)
 *   2 Last token      -> meter -> END with the token
 *   3 Help
 */
final class Ussd
{
    public function __construct(private CoreClient $core) {}

    public function handle(string $sessionId, string $phone, string $text): string
    {
        $in = $text === '' ? [] : explode('*', $text);
        // "0" goes back to the main menu from anywhere.
        if (($k = array_search('0', $in, true)) !== false && $k > 0) {
            $in = array_slice($in, $k + 1);
        }
        $msisdn = substr(preg_replace('/\D/', '', $phone), -8);

        if ($in === []) {
            return "CON Maru Quick - BPC Electricity\n1. Buy electricity\n2. Get my last token\n3. Help";
        }
        return match ($in[0]) {
            '1' => $this->buy($sessionId, $msisdn, array_slice($in, 1)),
            '2' => $this->reprint(array_slice($in, 1)),
            '3' => "END Buy BPC prepaid electricity on *XXX#.\nTokens are sent by SMS.\nHelp: call Maru Quick on [number], 24 hours.",
            default => "END Invalid choice. Please dial again.",
        };
    }

    private function buy(string $sessionId, string $msisdn, array $in): string
    {
        if (count($in) === 0) {
            return "CON Enter meter number:";
        }
        $meter = preg_replace('/\D/', '', $in[0]);
        if (!preg_match('/^\d{11,13}$/', $meter)) {
            return "END Meter number must be 11 to 13 digits. Please dial again.";
        }
        if (count($in) === 1) {
            return "CON Enter amount in Pula (minimum P10):";
        }
        $amount = (float) $in[1];
        // Confirm with BPC once per session (idempotency key = session), then reuse the quote.
        [$code, $q] = $this->core->call('POST', '/v1/confirm', [
            'meter' => $meter, 'amount' => $amount, 'msisdn' => $msisdn, 'idempotency_key' => 'ussd-' . $sessionId,
        ]);
        if ($code !== 200) {
            return 'END ' . ($q['message'] ?? 'Could not confirm meter. Please try again.');
        }
        if (count($in) === 2) {
            return sprintf("CON Meter %s\n%s\nAmount P%s\n1. Confirm\n2. Cancel", $q['meter_number'], $q['customer_name'], $q['amount']);
        }
        if ($in[2] !== '1') {
            return "END Cancelled. You have not been charged.";
        }
        if (count($in) === 3) {
            return "CON Pay with:\n1. Orange Money\n2. Mascom MyZaka\n3. BTC Smega";
        }
        $method = ['1' => 'orange-money', '2' => 'myzaka', '3' => 'smega'][$in[3]] ?? null;
        if (!$method) {
            return "END Invalid choice. You have not been charged.";
        }
        [$code, $s] = $this->core->call('POST', '/v1/vend', ['sale_id' => $q['sale_id']]);
        if ($code !== 200) {
            return 'END ' . ($s['message'] ?? 'Could not start the sale.');
        }
        // The wallet sends the customer a payment prompt; its callback confirms payment to the core
        // (see channels/public/index.php /pay/callback). In the test environment it is approved at once.
        PaymentGateway::requestPush($method, $msisdn, (int) $q['sale_id'], (string) $q['amount'], 'ussd');
        return sprintf("END Approve the P%s payment prompt on your phone.\nYour token will be sent by SMS to %s.\nReceipt %s",
            $q['amount'], $msisdn, $q['receipt_no']);
    }

    private function reprint(array $in): string
    {
        if (count($in) === 0) {
            return "CON Enter meter number:";
        }
        [$code, $s] = $this->core->call('POST', '/v1/reprint', ['meter' => preg_replace('/\D/', '', $in[0])]);
        if ($code !== 200 || empty($s['receipt'])) {
            return "END No token found for that meter.";
        }
        $r = $s['receipt'];
        return "END Meter {$r['meter_number']}\nToken: {$r['token']}\n{$r['kwh']} kWh, P{$r['transaction_amount']}\n{$r['date']}";
    }
}
