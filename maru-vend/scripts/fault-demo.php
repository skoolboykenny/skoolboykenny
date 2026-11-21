<?php
declare(strict_types=1);

/**
 * Site visit demonstration of failed-transaction handling (clause 7.9, Annex E).
 * Injects each fault into the BPC simulator, sells one token through the real API and
 * queue workers, and prints what the customer saw, the float effect and the sale history.
 *
 *   php scripts/fault-demo.php [--api=http://127.0.0.1:8080]
 */

require __DIR__ . '/../vendor/autoload.php';

use MaruVend\Api\HmacAuth;
use MaruVend\App;

$api = 'http://127.0.0.1:8080';
foreach ($argv as $a) {
    if (str_starts_with($a, '--api=')) {
        $api = substr($a, 6);
    }
}
$app = App::boot();
$sim = rtrim($app->settings->endpoint(), '/');

function call(string $api, string $method, string $path, array $body = []): array
{
    $json = $body ? json_encode($body) : '';
    $ts = (string) time();
    $ch = curl_init($api . $path);
    curl_setopt_array($ch, [CURLOPT_CUSTOMREQUEST => $method, CURLOPT_RETURNTRANSFER => true, CURLOPT_POSTFIELDS => $json ?: null,
        CURLOPT_HTTPHEADER => ['Content-Type: application/json', 'X-MV-Key: pos-demo', "X-MV-Timestamp: $ts",
            'X-MV-Signature: ' . HmacAuth::sign('pos-demo-secret', $ts, $method, $path, $json)]]);
    return json_decode((string) curl_exec($ch), true) ?: [];
}

function simMode(string $sim, string $mode, float $resolveAfter = 5): void
{
    $ch = curl_init("$sim/_sim/mode");
    curl_setopt_array($ch, [CURLOPT_POST => true, CURLOPT_RETURNTRANSFER => true,
        CURLOPT_POSTFIELDS => json_encode(['mode' => $mode, 'count' => 1, 'resolve_after_s' => $resolveAfter])]);
    curl_exec($ch);
}

$scenarios = [
    ['ok', '94949494949', 'Normal sale'],
    ['reject', '94949494949', 'BPC refuses the sale (business rule fault)'],
    ['processing', '94949494949', 'BPC slow to confirm: "Processing", resolved by last response'],
    ['lost', '94949494949', 'Response lost after BPC issued the token: recovered, never re-vended'],
    ['lostfail', '94949494949', 'Response lost and BPC issued nothing: confirmed failed, float released'],
    ['down', '94949494949', 'BPC gateway unavailable mid-request: outcome checked before any refund'],
];

foreach ($scenarios as $i => [$mode, $meter, $title]) {
    echo "\n=== " . ($i + 1) . ". $title  [simulator mode: $mode]\n";
    $float0 = $app->float()->position();
    simMode($sim, $mode, 4);
    $q = call($api, 'POST', '/v1/confirm', ['meter' => $meter, 'amount' => 50, 'idempotency_key' => "fault-$mode-" . bin2hex(random_bytes(3))]);
    if (!isset($q['sale_id'])) {
        echo '  confirm refused: ' . json_encode($q) . "\n";
        continue;
    }
    echo "  Customer confirmed: {$q['customer_name']}, meter {$q['meter_number']}, P{$q['amount']}\n";
    $s = call($api, 'POST', '/v1/vend', ['sale_id' => $q['sale_id']]);
    $seen = [];
    $t0 = time();
    do {
        sleep(1);
        $s = call($api, 'GET', "/v1/vend/{$q['sale_id']}");
        if (!in_array($s['message'], $seen, true)) {
            $seen[] = $s['message'];
            printf("  [%3ds] customer sees: %s\n", time() - $t0, $s['message']);
        }
    } while (!in_array($s['status'], ['SUCCEEDED', 'FAILED', 'MANUAL_REVIEW'], true) && time() - $t0 < 90);
    $float1 = $app->float()->position();
    printf("  Final: %s%s\n", $s['status'], isset($s['receipt']) ? "  token {$s['receipt']['token']}, {$s['receipt']['kwh']} kWh" : '');
    printf("  Float available P%.2f -> P%.2f (reserved P%.2f)\n", $float0['available'] / 100, $float1['available'] / 100, $float1['reserved'] / 100);
    $ev = $app->pdo->prepare('SELECT to_state, cause FROM sale_events WHERE sale_id = ? ORDER BY seq');
    $ev->execute([$q['sale_id']]);
    foreach ($ev->fetchAll() as $e) {
        echo "    -> {$e['to_state']}: {$e['cause']}\n";
    }
    $c = $app->pdo->prepare("SELECT COUNT(*) FROM vend_messages WHERE sale_id = ? AND operation = 'creditvend' AND direction = 'req'");
    $c->execute([$q['sale_id']]);
    echo '  Credit vend requests sent to BPC: ' . $c->fetchColumn() . "\n";
}
