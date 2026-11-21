<?php
declare(strict_types=1);

namespace MaruVend;

/**
 * Deployment configuration from environment variables.
 * Secrets (DB password, provider credentials, audit anchor key) live outside the code and web root.
 */
final class Config
{
    public static function env(string $key, ?string $default = null): ?string
    {
        $v = getenv($key);
        return $v === false || $v === '' ? $default : $v;
    }

    public static function db(): array
    {
        return [
            'host' => self::env('MV_DB_HOST', '127.0.0.1'),
            'port' => (int) self::env('MV_DB_PORT', '3306'),
            'name' => self::env('MV_DB_NAME', 'maruvend'),
            'user' => self::env('MV_DB_USER', 'maruvend'),
            'pass' => self::env('MV_DB_PASS', ''),
        ];
    }

    /** Directory outside the database where signed audit anchors are copied (WORM/offsite in production). */
    public static function anchorDir(): string
    {
        return self::env('MV_ANCHOR_DIR', sys_get_temp_dir() . '/maruvend-anchors');
    }

    /** Path to the audit anchor signing key. DB administrators must not have read access to it. */
    public static function anchorKeyFile(): string
    {
        return self::env('MV_ANCHOR_KEY_FILE', sys_get_temp_dir() . '/maruvend-anchor.key');
    }
}
