<?php
declare(strict_types=1);

namespace MaruVend\Channels;

use MaruVend\Api\HmacAuth;

/**
 * Calls the Maru Vend core API as one channel. The channel's HMAC secret stays on this server:
 * browsers, phones and the USSD aggregator never see it.
 */
final class CoreClient
{
    public function __construct(private string $baseUrl, private string $key, private string $secret) {}

    /** Build a client for a channel (web, app, pos, ussd) from MV_KEY_<CH>/MV_SECRET_<CH>; demo keys by default. */
    public static function forChannel(string $channel): self
    {
        $ch = strtoupper($channel);
        $demoKey = strtolower($channel) . '-demo';
        return new self(
            getenv('MV_CORE_URL') ?: 'http://127.0.0.1:8080',
            getenv("MV_KEY_$ch") ?: $demoKey,
            getenv("MV_SECRET_$ch") ?: "$demoKey-secret",
        );
    }

    /** @return array{0:int,1:array} HTTP status and decoded body */
    public function call(string $method, string $path, array $body = []): array
    {
        $json = $body ? json_encode($body) : '';
        $ts = (string) time();
        $pathOnly = (string) parse_url($path, PHP_URL_PATH);
        $ch = curl_init(rtrim($this->baseUrl, '/') . $path);
        curl_setopt_array($ch, [
            CURLOPT_CUSTOMREQUEST => $method,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_POSTFIELDS => $json !== '' ? $json : null,
            CURLOPT_TIMEOUT => 60,
            CURLOPT_HTTPHEADER => [
                'Content-Type: application/json',
                'X-MV-Key: ' . $this->key,
                'X-MV-Timestamp: ' . $ts,
                'X-MV-Signature: ' . HmacAuth::sign($this->secret, $ts, $method, $pathOnly, $json),
            ],
        ]);
        $raw = curl_exec($ch);
        $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        if ($raw === false) {
            return [503, ['error' => 'CORE_UNAVAILABLE', 'message' => 'Service temporarily unavailable. Please try again.']];
        }
        return [$status, json_decode((string) $raw, true) ?: []];
    }
}
