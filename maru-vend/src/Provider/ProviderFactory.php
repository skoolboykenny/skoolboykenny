<?php
declare(strict_types=1);

namespace MaruVend\Provider;

use MaruVend\Config;
use MaruVend\Settings;

final class ProviderFactory
{
    public static function make(Settings $settings): VendProvider
    {
        return match ($settings->get('provider')) {
            // The simulator speaks the aggregator REST API; credentials are dummies.
            'simulator' => new RestVendProvider($settings, 'sim-key', 'sim-pass', 'MARU-SIM', 'maru-vend', 'simulator'),
            'aggregator' => new RestVendProvider(
                $settings,
                (string) Config::env('MV_AGG_KEY'),
                (string) Config::env('MV_AGG_PASS'),
                (string) Config::env('MV_AGG_OUTLET'),
                (string) Config::env('MV_AGG_OPERATOR', 'maru-vend'),
                'aggregator'
            ),
            // 'xmlvend' => XMLVend 2.1 SOAP client for BPC CONLOG: added once BPC supplies its WSDL/XSDs.
            default => throw new \RuntimeException('Unsupported provider ' . $settings->get('provider')),
        };
    }
}
