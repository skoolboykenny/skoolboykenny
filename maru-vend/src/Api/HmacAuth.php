<?php
declare(strict_types=1);

namespace MaruVend\Api;

use PDO;

/**
 * Channel authentication. Each channel signs every request:
 *
 *   X-MV-Key:        channel API key
 *   X-MV-Timestamp:  unix seconds (must be within 300 s of server time)
 *   X-MV-Signature:  hex HMAC-SHA256(secret, timestamp + "\n" + METHOD + "\n" + path + "\n" + body)
 *
 * Combined with TLS 1.2+ this authenticates the channel, protects the request from tampering
 * and limits replay.
 */
final class HmacAuth
{
    public const SKEW_S = 300;

    public function __construct(private PDO $pdo) {}

    /** @return array|null the channel row, or null if authentication fails */
    public function verify(string $key, string $timestamp, string $signature, string $method, string $path, string $body): ?array
    {
        if (!ctype_digit($timestamp) || abs(time() - (int) $timestamp) > self::SKEW_S) {
            return null;
        }
        $st = $this->pdo->prepare('SELECT c.* FROM channels c JOIN merchants m ON m.id = c.merchant_id WHERE c.api_key = ? AND c.active = 1 AND m.active = 1');
        $st->execute([$key]);
        $ch = $st->fetch();
        if (!$ch) {
            return null;
        }
        $expect = self::sign($ch['api_secret'], $timestamp, $method, $path, $body);
        return hash_equals($expect, strtolower($signature)) ? $ch : null;
    }

    public static function sign(string $secret, string $timestamp, string $method, string $path, string $body): string
    {
        return hash_hmac('sha256', $timestamp . "\n" . strtoupper($method) . "\n" . $path . "\n" . $body, $secret);
    }
}
