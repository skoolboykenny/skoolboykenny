<?php
declare(strict_types=1);

namespace MaruVend\Provider;

/**
 * Normalised outcome of one call to the upstream vending system.
 *
 *  OK              definitive success (customer confirmed, or token issued)
 *  BUSINESS_FAULT  definitive refusal, no token (bad meter, amount out of range, ...)
 *  SYSTEM_FAULT    request provably not processed (connection refused, auth error); safe to retry
 *  UNKNOWN         request may have been processed; outcome must be recovered with lastResponse
 *  PENDING         lastResponse not ready yet; ask again later
 *  NOT_FOUND       lastResponse: provider has no such sale (it never arrived)
 *  DUPLICATE       sale reference already exists upstream; recover with lastResponse
 */
final class ProviderResult
{
    public const OK = 'OK';
    public const BUSINESS_FAULT = 'BUSINESS_FAULT';
    public const SYSTEM_FAULT = 'SYSTEM_FAULT';
    public const UNKNOWN = 'UNKNOWN';
    public const PENDING = 'PENDING';
    public const NOT_FOUND = 'NOT_FOUND';
    public const DUPLICATE = 'DUPLICATE';

    public function __construct(
        public readonly string $outcome,
        public readonly array $data = [],
        public readonly ?string $faultCode = null,
        public readonly ?string $message = null,
        public readonly ?int $retryAfterS = null,
        public readonly array $exchange = [], // ['request' => ..., 'response' => ..., 'http' => int]
    ) {}

    public function ok(): bool
    {
        return $this->outcome === self::OK;
    }
}
