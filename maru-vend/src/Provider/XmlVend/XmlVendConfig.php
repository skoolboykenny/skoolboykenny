<?php
declare(strict_types=1);

namespace MaruVend\Provider\XmlVend;

use MaruVend\Config;

/** Connection details agreed with BPC and its server supplier (values from environment / vault). */
final class XmlVendConfig
{
    public function __construct(
        public readonly string $clientEan,          // our client ID: 13-digit EAN issued by BPC
        public readonly string $opName,             // operator name (max 10 chars)
        public readonly ?string $password,
        public readonly string $version = '2.1',    // in the namespaces (5.2.2.2)
        public readonly string $currency = 'BWP',
        public readonly string $path = '/xmlvend',  // appended to the BPC endpoint setting
        public readonly ?string $clientCert = null, // mutual TLS
        public readonly ?string $clientKey = null,
        public readonly ?string $caFile = null,
        public readonly string $terminalPrefix = 'MV',
    ) {}

    public static function fromEnv(): self
    {
        return new self(
            (string) Config::env('MV_XV_CLIENT_EAN', '0000000000000'),
            (string) Config::env('MV_XV_OPNAME', 'maruvend'),
            Config::env('MV_XV_PASSWORD'),
            (string) Config::env('MV_XV_VERSION', '2.1'),
            (string) Config::env('MV_XV_CURRENCY', 'BWP'),
            (string) Config::env('MV_XV_PATH', '/xmlvend'),
            Config::env('MV_XV_CLIENT_CERT'),
            Config::env('MV_XV_CLIENT_KEY'),
            Config::env('MV_XV_CA_FILE'),
            (string) Config::env('MV_XV_TERMINAL_PREFIX', 'MV'),
        );
    }

    public function baseNs(): string
    {
        return "http://www.nrs.eskom.co.za/xmlvend/base/{$this->version}/schema";
    }

    public function revenueNs(): string
    {
        return "http://www.nrs.eskom.co.za/xmlvend/revenue/{$this->version}/schema";
    }
}
