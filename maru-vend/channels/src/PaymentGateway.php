<?php
declare(strict_types=1);

namespace MaruVend\Channels;

/**
 * Customer payments for app, web store and USSD.
 *
 * Production: each method maps to the contracted provider (Orange Money Web Payment API, Mascom MyZaka,
 * BTC Smega, card acquirer). The provider calls back /pay/callback when the customer has paid, and only
 * then is the sale released to the vend queue. If BPC then fails to issue a token, the payment is
 * reversed; once a token is issued there is no refund, only free reprints.
 *
 * Test environment (MV_PAYMENTS=test, the default): payments are approved immediately and clearly
 * labelled as test payments. No real money moves.
 */
final class PaymentGateway
{
    public const METHODS = [
        'orange-money' => 'Orange Money',
        'myzaka' => 'Mascom MyZaka',
        'smega' => 'BTC Smega',
        'card' => 'Debit or credit card',
    ];

    public static function testMode(): bool
    {
        return (getenv('MV_PAYMENTS') ?: 'test') === 'test';
    }

    /** Ask the wallet to push a payment prompt to the customer's phone. */
    public static function requestPush(string $method, string $msisdn, int $saleId, string $amount, string $channel): void
    {
        if (!isset(self::METHODS[$method])) {
            throw new \InvalidArgumentException('Unknown payment method');
        }
        if (self::testMode()) {
            self::confirm($channel, $saleId, 'TEST-' . strtoupper($method) . '-' . $saleId);
            return;
        }
        throw new \RuntimeException("Payment provider for $method is not configured");
    }

    /** Payment confirmed (provider callback, or test approval): release the sale to the queue. */
    public static function confirm(string $channel, int $saleId, string $paymentRef): array
    {
        return CoreClient::forChannel($channel)->call('POST', "/v1/sales/$saleId/payment", ['payment_ref' => $paymentRef]);
    }
}
