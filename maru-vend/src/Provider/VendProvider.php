<?php
declare(strict_types=1);

namespace MaruVend\Provider;

/**
 * Port to the upstream electricity vending system. The vend core only ever talks to this
 * interface, so the XMLVend 2.1 client for BPC CONLOG, the existing aggregator API and the
 * test simulator are interchangeable adapters.
 *
 * creditVend result data (on OK) uses these normalised keys:
 *   token, keyChange1, keyChange2, kwh, costUnitsThebe, fixedChargeThebe, govLevyThebe,
 *   vatThebe, totalThebe, tariffIndex, customerName, providerRef, unitRateThebe
 */
interface VendProvider
{
    public function name(): string;

    /** Validate the meter and return customerName (no token issued, no money spent). */
    public function confirmCustomer(string $clientSaleId, string $meter, int $amountThebe, string $terminal): ProviderResult;

    /** Issue the token. Final: cannot be reversed. */
    public function creditVend(string $clientSaleId, string $meter, int $amountThebe, string $terminal): ProviderResult;

    /** Recover the outcome of a previous creditVend by its clientSaleId. */
    public function lastResponse(string $clientSaleId): ProviderResult;
}
