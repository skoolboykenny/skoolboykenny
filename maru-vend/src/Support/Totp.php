<?php
declare(strict_types=1);

namespace MaruVend\Support;

/** RFC 6238 time-based one-time passwords (works with Google/Microsoft Authenticator). */
final class Totp
{
    private const B32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

    public static function newSecret(): string
    {
        $s = '';
        foreach (str_split(random_bytes(20)) as $b) {
            $s .= self::B32[ord($b) % 32];
        }
        return $s;
    }

    public static function code(string $secret, ?int $time = null): string
    {
        $counter = intdiv($time ?? time(), 30);
        $hash = hash_hmac('sha1', pack('N*', 0, $counter), self::decode($secret), true);
        $o = ord($hash[19]) & 0xf;
        $n = ((ord($hash[$o]) & 0x7f) << 24) | (ord($hash[$o + 1]) << 16) | (ord($hash[$o + 2]) << 8) | ord($hash[$o + 3]);
        return str_pad((string) ($n % 1_000_000), 6, '0', STR_PAD_LEFT);
    }

    /** Accept the current code and one step either side for clock drift. */
    public static function verify(string $secret, string $code): bool
    {
        foreach ([-30, 0, 30] as $d) {
            if (hash_equals(self::code($secret, time() + $d), $code)) {
                return true;
            }
        }
        return false;
    }

    public static function uri(string $secret, string $user): string
    {
        return 'otpauth://totp/MaruVend:' . rawurlencode($user) . "?secret=$secret&issuer=MaruVend";
    }

    private static function decode(string $s): string
    {
        $bits = '';
        foreach (str_split(strtoupper($s)) as $c) {
            $bits .= str_pad(decbin(strpos(self::B32, $c)), 5, '0', STR_PAD_LEFT);
        }
        $out = '';
        foreach (str_split($bits, 8) as $byte) {
            if (strlen($byte) === 8) {
                $out .= chr(bindec($byte));
            }
        }
        return $out;
    }
}
