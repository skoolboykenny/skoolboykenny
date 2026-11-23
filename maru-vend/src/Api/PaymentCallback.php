<?php
declare(strict_types=1);

namespace MaruVend\Api;

/**
 * Authenticates payment confirmations sent by a payment provider or bank (Orange Money, MyZaka,
 * Smega, card acquirer, FNB and other banks). Each provider gets its own shared secret,
 * MV_PAY_SECRET_<PROVIDER>, and signs every callback:
 *
 *   X-Pay-Timestamp: unix seconds (within 300 s)
 *   X-Pay-Signature: hex HMAC-SHA256(secret, timestamp + "\n" + body)
 *   body:            {"sale_id": 123, "payment_ref": "...", "amount_thebe": 2500}
 *
 * Where a provider uses its own signing scheme, an adapter converts it to this check.
 */
final class PaymentCallback
{
    public static function secret(string $provider): ?string
    {
        if (!preg_match('/^[a-z0-9-]{2,32}$/', $provider)) {
            return null;
        }
        $v = getenv('MV_PAY_SECRET_' . strtoupper(str_replace('-', '_', $provider)));
        return $v === false || $v === '' ? null : $v;
    }

    public static function sign(string $secret, string $timestamp, string $body): string
    {
        return hash_hmac('sha256', $timestamp . "\n" . $body, $secret);
    }

    public static function verify(string $provider, string $timestamp, string $signature, string $body): bool
    {
        $secret = self::secret($provider);
        if ($secret === null || !ctype_digit($timestamp) || abs(time() - (int) $timestamp) > HmacAuth::SKEW_S) {
            return false;
        }
        return hash_equals(self::sign($secret, $timestamp, $body), strtolower($signature));
    }
}
