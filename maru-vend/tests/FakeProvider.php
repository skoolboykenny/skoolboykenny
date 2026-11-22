<?php
declare(strict_types=1);

namespace MaruVend\Tests;

use MaruVend\Provider\ProviderResult;
use MaruVend\Provider\VendProvider;

/** Scripted provider: queue the outcomes the next calls should return. */
final class FakeProvider implements VendProvider
{
    /** @var list<ProviderResult> */
    public array $vendQueue = [];
    /** @var list<ProviderResult> */
    public array $adviceQueue = [];
    public array $calls = [];

    public function name(): string
    {
        return 'fake';
    }

    public function confirmCustomer(string $clientSaleId, string $meter, int $amountThebe, string $terminal): ProviderResult
    {
        $this->calls[] = ['confirm', $clientSaleId];
        return $meter === '07070707070'
            ? new ProviderResult(ProviderResult::BUSINESS_FAULT, [], '108', 'Meter blocked')
            : new ProviderResult(ProviderResult::OK, ['customerName' => 'Test Customer']);
    }

    public function creditVend(string $clientSaleId, string $meter, int $amountThebe, string $terminal): ProviderResult
    {
        $this->calls[] = ['vend', $clientSaleId];
        return array_shift($this->vendQueue) ?? self::token();
    }

    public function lastResponse(string $clientSaleId): ProviderResult
    {
        $this->calls[] = ['advice', $clientSaleId];
        return array_shift($this->adviceQueue) ?? new ProviderResult(ProviderResult::PENDING);
    }

    public static function token(string $token = '12345678901234567890'): ProviderResult
    {
        return new ProviderResult(ProviderResult::OK, [
            'token' => $token, 'keyChange1' => null, 'keyChange2' => null, 'kwh' => 15.2, 'costUnitsThebe' => 1840,
            'fixedChargeThebe' => 0, 'govLevyThebe' => 38, 'vatThebe' => 307, 'totalThebe' => 2500, 'tariffIndex' => '01',
            'customerName' => 'Test Customer', 'providerRef' => 'T1', 'unitRateThebe' => 121,
        ]);
    }

    public function vendCalls(): int
    {
        return count(array_filter($this->calls, fn ($c) => $c[0] === 'vend'));
    }
}
