<?php
declare(strict_types=1);

namespace MaruVend\Provider;

use MaruVend\Config;
use MaruVend\Provider\XmlVend\XmlVendConfig;
use MaruVend\Provider\XmlVend\XmlVendProvider;
use MaruVend\Settings;
use PDO;

final class ProviderFactory
{
    /**
     * @param string $process who is calling (a queue worker's id, or "api"); XMLVend gives each its
     *                        own terminal ID so per-terminal "last response" is never ambiguous.
     */
    public static function make(Settings $settings, ?PDO $pdo = null, string $process = 'api'): VendProvider
    {
        return match ($settings->get('provider')) {
            // The simulator speaks the aggregator REST API; credentials are dummies.
            // Built-in test tokens, no outside connection (hosting before a token source is contracted).
            'test' => new TestProvider(),
            'simulator' => new RestVendProvider($settings, 'sim-key', 'sim-pass', 'MARU-SIM', 'maru-vend', 'simulator'),
            'aggregator' => new RestVendProvider(
                $settings,
                (string) Config::env('MV_AGG_KEY'),
                (string) Config::env('MV_AGG_PASS'),
                (string) Config::env('MV_AGG_OUTLET'),
                (string) Config::env('MV_AGG_OPERATOR', 'maru-vend'),
                'aggregator'
            ),
            // XMLVend 2.1 SOAP client for BPC CONLOG (clause 7.1). With the BPC simulator for testing,
            // set bpc_endpoint to the simulator and provider to 'xmlvend'.
            'xmlvend' => new XmlVendProvider(
                $settings,
                $pdo ?? throw new \RuntimeException('XMLVend provider needs the database'),
                XmlVendConfig::fromEnv(),
                self::terminalId($process),
            ),
            default => throw new \RuntimeException('Unsupported provider ' . $settings->get('provider')),
        };
    }

    /** Stable terminal ID per process, e.g. MV-W3F9A1C02 (GenericDeviceID, max 160 chars). */
    public static function terminalId(string $process): string
    {
        $prefix = (string) Config::env('MV_XV_TERMINAL_PREFIX', 'MV');
        return $prefix . '-' . ($process === 'api' ? 'API' : 'W') . strtoupper(substr(hash('sha256', (string) gethostname() . '|' . $process), 0, 8));
    }
}
