<?php
declare(strict_types=1);

namespace MaruVend\Vend;

/** A request the platform refuses, with a code and a customer-safe message. */
final class VendException extends \RuntimeException
{
    public function __construct(public readonly string $errorCode, string $message, public readonly int $httpStatus = 422)
    {
        parent::__construct($message);
    }
}
