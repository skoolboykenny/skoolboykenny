<?php
declare(strict_types=1);

namespace MaruVend\Provider;

use MaruVend\Settings;

/**
 * Adapter for the aggregator REST vending API (trialvend / creditvend / advice), the flow
 * Maru Quick already uses in production. The BPC simulator speaks the same API so this adapter
 * is exercised end to end in testing and at the site visit.
 *
 * Mapping of upstream responses (per the aggregator's published API):
 *   200 code "0"                  -> OK
 *   499 code "133" "Processing"   -> UNKNOWN on creditvend / PENDING on advice
 *   500 code "06"  "Processing"   -> PENDING (advice window not open yet)
 *   409 code "09"/"20" Duplicate  -> DUPLICATE
 *   404 code "209"                -> NOT_FOUND
 *   401 codes 02/04/11            -> SYSTEM_FAULT (credentials) - nothing processed
 *   other 4xx/5xx with a code     -> BUSINESS_FAULT
 *   connection refused / DNS fail -> SYSTEM_FAULT (request never left)
 *   timeout after sending         -> UNKNOWN
 */
final class RestVendProvider implements VendProvider
{
    public function __construct(
        private Settings $settings,
        private string $apiKey,
        private string $apiPassword,
        private string $outletId,
        private string $operatorId,
        private string $name = 'rest',
    ) {}

    public function name(): string
    {
        return $this->name;
    }

    public function confirmCustomer(string $clientSaleId, string $meter, int $amountThebe, string $terminal): ProviderResult
    {
        $r = $this->post('/electricity/trialvend', $this->saleBody($clientSaleId, $meter, $amountThebe, $terminal));
        if ($r->ok()) {
            return new ProviderResult(ProviderResult::OK, [
                'customerName' => $r->data['custVendDetail']['name'] ?? null,
                'meterNumber' => $r->data['custVendDetail']['meterNumber'] ?? $meter,
            ], exchange: $r->exchange);
        }
        // A trial vend never issues a token, so an uncertain outcome is just a failure to confirm.
        return $r->outcome === ProviderResult::UNKNOWN
            ? new ProviderResult(ProviderResult::SYSTEM_FAULT, [], $r->faultCode, 'Could not confirm meter in time', exchange: $r->exchange)
            : $r;
    }

    public function creditVend(string $clientSaleId, string $meter, int $amountThebe, string $terminal): ProviderResult
    {
        $r = $this->post('/electricity/creditvend', $this->saleBody($clientSaleId, $meter, $amountThebe, $terminal));
        return $r->ok() ? $this->normaliseReceipt($r) : $r;
    }

    public function lastResponse(string $clientSaleId): ProviderResult
    {
        $r = $this->post('/electricity/advice', ['clientSaleId' => $clientSaleId, 'outletId' => $this->outletId], true);
        if ($r->ok()) {
            return $this->normaliseReceipt($r);
        }
        return $r;
    }

    private function saleBody(string $clientSaleId, string $meter, int $amountThebe, string $terminal): array
    {
        return [
            'meterNumber' => $meter,
            'transactionAmount' => $amountThebe / 100,
            'terminalId' => $terminal,
            'clientSaleId' => $clientSaleId,
            'outletId' => $this->outletId,
            'operatorId' => $this->operatorId,
        ];
    }

    private function normaliseReceipt(ProviderResult $r): ProviderResult
    {
        $rc = $r->data['creditVendReceipt'] ?? [];
        if (empty($rc['stsCipher'])) {
            // A "success" with no token cannot be trusted; treat as unknown and recover via advice.
            return new ProviderResult(ProviderResult::UNKNOWN, [], $r->faultCode, 'Success without token', exchange: $r->exchange);
        }
        $t = fn ($v) => (int) round(((float) ($v ?? 0)) * 100);
        $rate = null;
        if (!empty($rc['tariffBreakdown'][0]['rate'])) {
            $rate = $t($rc['tariffBreakdown'][0]['rate']);
        }
        return new ProviderResult(ProviderResult::OK, [
            'token' => (string) $rc['stsCipher'],
            'keyChange1' => $rc['keychangetoken1'] ?? null,
            'keyChange2' => $rc['keychangetoken2'] ?? null,
            'kwh' => (float) ($rc['tokenUnits'] ?? 0),
            'costUnitsThebe' => $t($rc['costUnits'] ?? 0),
            'fixedChargeThebe' => $t($rc['standardCharge'] ?? 0),
            'govLevyThebe' => $t($rc['governmentLevy'] ?? 0),
            'vatThebe' => $t($rc['vat'] ?? 0),
            'totalThebe' => $t($rc['amtTendered'] ?? ($r->data['transactionAmount'] ?? 0)),
            'tariffIndex' => $rc['ti'] ?? ($rc['tariff'] ?? null),
            'customerName' => $rc['name'] ?? null,
            'providerRef' => $r->data['transactionId'] ?? ($rc['receiptNo'] ?? null),
            'unitRateThebe' => $rate,
        ], exchange: $r->exchange);
    }

    private function post(string $path, array $body, bool $isAdvice = false): ProviderResult
    {
        $url = rtrim($this->settings->endpoint(), '/') . $path; // read every call: endpoint switch needs no restart
        $json = json_encode($body);
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => $json,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_HTTPHEADER => [
                'Content-Type: application/json',
                'Authorization: Basic ' . base64_encode($this->apiKey . ':' . $this->apiPassword),
            ],
            CURLOPT_CONNECTTIMEOUT => 10,
            CURLOPT_TIMEOUT => $this->settings->workerTimeout(), // mapped to BPC's timeout (clause 7.8)
            CURLOPT_SSL_VERIFYPEER => true,                      // never disabled
            CURLOPT_SSL_VERIFYHOST => 2,
        ]);
        $raw = curl_exec($ch);
        $errno = curl_errno($ch);
        $http = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        $err = curl_error($ch);
        curl_close($ch);
        $exchange = ['request' => $json, 'response' => is_string($raw) ? $raw : "curl error $errno: $err", 'http' => $http, 'path' => $path];

        if ($raw === false) {
            $neverSent = in_array($errno, [CURLE_COULDNT_CONNECT, CURLE_COULDNT_RESOLVE_HOST, CURLE_SSL_CONNECT_ERROR, 60 /* peer cert */], true);
            if ($neverSent || $isAdvice) {
                return new ProviderResult(ProviderResult::SYSTEM_FAULT, [], "CURL$errno", $err, exchange: $exchange);
            }
            return new ProviderResult(ProviderResult::UNKNOWN, [], "CURL$errno", 'No response within timeout', exchange: $exchange);
        }

        $data = json_decode($raw, true) ?: [];
        $code = isset($data['code']) ? (string) $data['code'] : null;
        $msg = $data['message'] ?? ($data['response'] ?? null);
        $retry = isset($data['retryAfter']) ? (int) $data['retryAfter'] : null;

        return match (true) {
            $http === 200 && ($code === '0' || $code === null) => new ProviderResult(ProviderResult::OK, $data, $code, exchange: $exchange),
            $http === 499 || $code === '133' => new ProviderResult($isAdvice ? ProviderResult::PENDING : ProviderResult::UNKNOWN, $data, $code, $msg, $retry, $exchange),
            $code === '06' => new ProviderResult(ProviderResult::PENDING, $data, $code, $msg, $retry, $exchange),
            $http === 409 || in_array($code, ['09', '20'], true) => new ProviderResult(ProviderResult::DUPLICATE, $data, $code, $msg, exchange: $exchange),
            $http === 404 || $code === '209' => new ProviderResult(ProviderResult::NOT_FOUND, $data, $code, $msg, exchange: $exchange),
            $http === 401 => new ProviderResult(ProviderResult::SYSTEM_FAULT, $data, $code, $msg, exchange: $exchange),
            $http >= 500 && $code === null => new ProviderResult($isAdvice ? ProviderResult::SYSTEM_FAULT : ProviderResult::UNKNOWN, $data, null, $msg, exchange: $exchange),
            default => new ProviderResult(ProviderResult::BUSINESS_FAULT, $data, $code, $msg, exchange: $exchange),
        };
    }
}
