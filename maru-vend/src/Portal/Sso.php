<?php
declare(strict_types=1);

namespace MaruVend\Portal;

use PDO;

/**
 * Sign-in hand-off from the Maru Quick website (maru_power_login.php) to Maru Power.
 *
 * The website checks the email and password against power_users in the Maru Quick database, then
 * sends the browser to /power/sso?t=<ticket>. A ticket is
 *
 *   base64url(json {"uid": 12, "exp": 1767000000, "n": "<random>"}) . "." . hex HMAC-SHA256(secret, first part)
 *
 * signed with a secret both sides share (MV_SSO_SECRET here, MQ_POWER_SSO_SECRET on the website).
 * It is valid for 60 seconds and only once: the nonce is recorded when used. No password ever
 * travels to Maru Power.
 */
final class Sso
{
    public const MAX_AGE_S = 60;

    public static function secret(): ?string
    {
        $s = getenv('MV_SSO_SECRET');
        return $s !== false && strlen($s) >= 32 ? $s : null;
    }

    public static function make(string $secret, int $uid, ?int $now = null): string
    {
        $body = rtrim(strtr(base64_encode(json_encode(['uid' => $uid, 'exp' => ($now ?? time()) + self::MAX_AGE_S, 'n' => bin2hex(random_bytes(16))])), '+/', '-_'), '=');
        return $body . '.' . hash_hmac('sha256', $body, $secret);
    }

    /** @return int|null the account id, or null if the ticket is bad, expired or already used */
    public static function redeem(PDO $pdo, string $secret, string $ticket, ?int $now = null): ?int
    {
        $parts = explode('.', $ticket);
        if (count($parts) !== 2 || !hash_equals(hash_hmac('sha256', $parts[0], $secret), strtolower($parts[1]))) {
            return null;
        }
        $d = json_decode((string) base64_decode(strtr($parts[0], '-_', '+/')), true);
        $now ??= time();
        if (!is_array($d) || !is_int($d['uid'] ?? null) || !is_int($d['exp'] ?? null) || !is_string($d['n'] ?? null)
            || $d['exp'] < $now || $d['exp'] > $now + self::MAX_AGE_S + 5 || !preg_match('/^[0-9a-f]{32}$/', $d['n'])) {
            return null;
        }
        try {
            $pdo->prepare('INSERT INTO portal_sso_nonces (nonce, user_id) VALUES (?, ?)')->execute([$d['n'], $d['uid']]);
        } catch (\PDOException $e) {
            return null; // used before
        }
        return $d['uid'];
    }
}
