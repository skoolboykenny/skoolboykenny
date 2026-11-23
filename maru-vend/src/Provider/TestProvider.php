<?php
declare(strict_types=1);

namespace MaruVend\Provider;

/**
 * TEST token source, built in: issues test tokens without any outside connection.
 * For running Maru Power on hosting before a real token source is contracted.
 * Set the setting provider=test. Test tokens do not load on a real meter.
 *
 * Any 11- or 13-digit meter is accepted, except ones starting 0000 (rejected, to test failures).
 * The token is derived from the sale id, so a repeated request returns the same token.
 */
final class TestProvider implements VendProvider
{
    private const RATE_THEBE = 160; // illustrative price per kWh, VAT inclusive

    public function name(): string
    {
        return 'test';
    }

    public function confirmCustomer(string $clientSaleId, string $meter, int $amountThebe, string $terminal): ProviderResult
    {
        if (str_starts_with($meter, '0000')) {
            return new ProviderResult(ProviderResult::BUSINESS_FAULT, [], 'TEST-BLOCKED', 'Meter not found');
        }
        return new ProviderResult(ProviderResult::OK, ['customerName' => 'Test customer ' . substr($meter, -4)]);
    }

    public function creditVend(string $clientSaleId, string $meter, int $amountThebe, string $terminal): ProviderResult
    {
        $c = $this->confirmCustomer($clientSaleId, $meter, $amountThebe, $terminal);
        if (!$c->ok()) {
            return $c;
        }
        $h = hash('sha256', 'maru-test-token|' . $clientSaleId);
        $token = '';
        foreach (str_split($h, 2) as $byte) {
            $token .= (string) (hexdec($byte) % 10);
            if (strlen($token) === 20) {
                break;
            }
        }
        $vat = (int) round($amountThebe * 14 / 114);
        $fixed = min(1000, intdiv($amountThebe, 10));
        $levy = (int) round(($amountThebe - $vat - $fixed) * 0.02);
        $units = $amountThebe - $vat - $fixed - $levy;
        return new ProviderResult(ProviderResult::OK, [
            'token' => $token, 'keyChange1' => null, 'keyChange2' => null,
            'kwh' => round($units / self::RATE_THEBE * 1.14, 1),
            'costUnitsThebe' => $units, 'fixedChargeThebe' => $fixed, 'govLevyThebe' => $levy, 'vatThebe' => $vat,
            'totalThebe' => $amountThebe, 'tariffIndex' => 'TEST', 'unitRateThebe' => self::RATE_THEBE,
            'customerName' => 'Test customer ' . substr($meter, -4), 'providerRef' => 'TEST-' . strtoupper(substr($h, 0, 10)),
        ]);
    }

    public function lastResponse(string $clientSaleId): ProviderResult
    {
        // In-process: a vend is never left uncertain, so there is nothing to recover.
        return new ProviderResult(ProviderResult::NOT_FOUND, [], null, 'No uncertain sale in the test source');
    }
}
