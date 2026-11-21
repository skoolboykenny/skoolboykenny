<?php
declare(strict_types=1);

namespace MaruVend\Support;

/** 26-character, time-ordered unique id (ULID) used as the upstream clientSaleId. */
final class Ulid
{
    private const ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';

    public static function generate(): string
    {
        $ms = (int) floor(microtime(true) * 1000);
        $time = '';
        for ($i = 9; $i >= 0; $i--) {
            $time = self::ALPHABET[$ms % 32] . $time;
            $ms = intdiv($ms, 32);
        }
        $rand = '';
        $bytes = random_bytes(16);
        for ($i = 0; $i < 16; $i++) {
            $rand .= self::ALPHABET[ord($bytes[$i]) % 32];
        }
        return $time . $rand;
    }
}
