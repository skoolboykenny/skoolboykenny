<?php
declare(strict_types=1);

namespace MaruVend\Vend;

/**
 * Sale lifecycle.
 *
 *  QUOTED ──► PAYMENT_PENDING ──► RESERVED ──► SUBMITTED ──► SUCCEEDED
 *    │              │                ▲            │  │
 *    ▼              ▼                └─(retry)────┘  ├──► FAILED (BPC confirmed no token; float released)
 *  EXPIRED        EXPIRED                            └──► UNKNOWN ──► SUCCEEDED | FAILED | MANUAL_REVIEW
 *
 * POS sales skip PAYMENT_PENDING (paid from merchant float). An UNKNOWN sale is never re-vended.
 */
final class SaleState
{
    public const QUOTED = 'QUOTED';
    public const PAYMENT_PENDING = 'PAYMENT_PENDING';
    public const RESERVED = 'RESERVED';
    public const SUBMITTED = 'SUBMITTED';
    public const SUCCEEDED = 'SUCCEEDED';
    public const FAILED = 'FAILED';
    public const UNKNOWN = 'UNKNOWN';
    public const MANUAL_REVIEW = 'MANUAL_REVIEW';
    public const EXPIRED = 'EXPIRED';

    public const TRANSITIONS = [
        null => [self::QUOTED],
        self::QUOTED => [self::PAYMENT_PENDING, self::RESERVED, self::EXPIRED],
        self::PAYMENT_PENDING => [self::RESERVED, self::EXPIRED],
        self::RESERVED => [self::SUBMITTED],
        self::SUBMITTED => [self::SUCCEEDED, self::FAILED, self::UNKNOWN, self::RESERVED],
        self::UNKNOWN => [self::SUCCEEDED, self::FAILED, self::MANUAL_REVIEW],
        self::MANUAL_REVIEW => [self::SUCCEEDED, self::FAILED],
        self::SUCCEEDED => [],
        self::FAILED => [],
        self::EXPIRED => [],
    ];

    /** States in which money is held but the outcome at BPC is not yet known. */
    public const UNRESOLVED = [self::UNKNOWN, self::MANUAL_REVIEW];

    public static function allowed(?string $from, string $to): bool
    {
        return in_array($to, self::TRANSITIONS[$from ?? ''] ?? [], true);
    }

    /** Message shown to the customer on every channel. */
    public static function customerMessage(string $state): string
    {
        return match ($state) {
            self::QUOTED => 'Please confirm the name and meter number.',
            self::PAYMENT_PENDING => 'Waiting for payment.',
            self::RESERVED, self::SUBMITTED => 'Getting your token...',
            self::UNKNOWN, self::MANUAL_REVIEW => 'Confirming your token, do not pay again. It will be sent by SMS.',
            self::SUCCEEDED => 'Token issued.',
            self::FAILED => 'A token could not be issued. You have not been charged.',
            self::EXPIRED => 'This request expired. Please start again.',
            default => '',
        };
    }
}
