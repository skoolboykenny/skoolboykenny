<?php
declare(strict_types=1);

/**
 * BPC vending simulator (TEST ENVIRONMENT ONLY).
 *
 * Speaks the same REST vending API as the aggregator Maru Quick already integrates with
 * (trialvend / creditvend / advice) so the real client code is exercised end to end, and lets
 * operators inject faults to demonstrate every failure path at the site visit:
 *
 *   POST /_sim/mode   {"mode": "...", "count": N}   next N credit vends behave as <mode>
 *       ok         normal success
 *       reject     business fault: meter blocked (no token)
 *       processing 499/133 "Processing"; advice resolves to success after resolve_after_s
 *       lost       request processed (token issued) but response never arrives (client times out)
 *       lostfail   no token issued and response never arrives (advice returns failure)
 *       down       503 with no body (gateway unavailable)
 *   GET  /_sim/stats  load seen by "BPC": total requests, peak concurrency, peak requests/second
 *   POST /_sim/reset
 *
 * Results of this simulator are never evidence of certification. Certification is done
 * against BPC's own test environment by BPC's authorised supplier.
 */

$dbFile = getenv('SIM_DB') ?: sys_get_temp_dir() . '/maruvend-sim.sqlite';
$db = new PDO('sqlite:' . $dbFile, null, null, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION, PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC]);
$db->exec('PRAGMA busy_timeout = 5000');
$db->exec('PRAGMA journal_mode = WAL');
$db->exec('CREATE TABLE IF NOT EXISTS sales (client_sale_id TEXT PRIMARY KEY, meter TEXT, amount REAL, outcome TEXT, created REAL, resolve_at REAL, receipt TEXT)');
$db->exec('CREATE TABLE IF NOT EXISTS mode (id INTEGER PRIMARY KEY CHECK (id = 1), mode TEXT, remaining INTEGER, resolve_after REAL, delay REAL)');
$db->exec('CREATE TABLE IF NOT EXISTS hits (t REAL, path TEXT, phase TEXT)');
$db->exec("INSERT OR IGNORE INTO mode VALUES (1, 'ok', 0, 5, 0.3)");

$method = $_SERVER['REQUEST_METHOD'];
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
$body = json_decode(file_get_contents('php://input') ?: '{}', true) ?: [];

function out(int $status, array $data): never
{
    http_response_code($status);
    header('Content-Type: application/json');
    echo json_encode($data);
    exit;
}

// Customers known to the simulated BPC. Any other 11-digit meter is "not found".
const METERS = [
    '04040404040' => ['name' => 'Kgosi Business Centre', 'ti' => '02', 'tariff' => 'Business'],
    '94949494949' => ['name' => 'Mpho Domestic', 'ti' => '01', 'tariff' => 'Domestic'],
    '01234567890' => ['name' => 'Naledi Clinic', 'ti' => '03', 'tariff' => 'Government'],
    '07070707070' => ['name' => 'Blocked Meter Test', 'ti' => '01', 'tariff' => 'Domestic', 'blocked' => true],
];

function receipt(string $id, string $meter, float $amount): array
{
    $m = METERS[$meter];
    // Simplified BPC-like breakdown: VAT 14% inclusive, 1.5% levy, P10 fixed charge if amount allows.
    $vat = round($amount * 14 / 114, 2);
    $levy = round($amount * 0.015, 2);
    $fixed = $amount >= 50 ? 10.00 : 0.00;
    $cost = round($amount - $vat - $levy - $fixed, 2);
    $rate = $m['ti'] === '02' ? 1.69 : 1.21;
    $kwh = round($cost / $rate, 1);
    $token = '';
    for ($i = 0; $i < 20; $i++) {
        $token .= (string) random_int(0, 9);
    }
    return [
        'code' => '0', 'clientSaleId' => $id, 'response' => 'Successful',
        'creditVendReceipt' => [
            'clientId' => 'MARU', 'account' => $meter, 'location' => 'Gaborone', 'name' => $m['name'],
            'date' => date('Y-m-d H:i:s'), 'receiptNo' => 'BPC' . random_int(100000, 999999), 'amtTendered' => $amount,
            'costUnits' => $cost, 'standardCharge' => $fixed, 'governmentLevy' => $levy, 'vat' => $vat,
            'desc' => 'Prepaid electricity', 'tariff' => $m['tariff'], 'tariffBreakdown' => [['units' => (string) $kwh, 'rate' => (string) $rate]],
            'tokenUnits' => (string) $kwh, 'meterType' => 'STS', 'krn' => '1', 'ti' => $m['ti'], 'meterNumber' => $meter,
            'sgc' => '600123', 'stsCipher' => $token,
        ],
        'transactionId' => 'T' . random_int(10000000, 99999999), 'transactionAmount' => $amount,
    ];
}

function hit(PDO $db, string $path, string $phase): void
{
    $db->prepare('INSERT INTO hits VALUES (?, ?, ?)')->execute([microtime(true), $path, $phase]);
}

// ------------------------------------------------------------------ control endpoints
if ($path === '/_sim/mode' && $method === 'POST') {
    $db->prepare('UPDATE mode SET mode = ?, remaining = ?, resolve_after = ? WHERE id = 1')
        ->execute([$body['mode'] ?? 'ok', (int) ($body['count'] ?? 1), (float) ($body['resolve_after_s'] ?? 5)]);
    out(200, ['ok' => true]);
}
if ($path === '/_sim/reset' && $method === 'POST') {
    $db->exec("DELETE FROM sales; DELETE FROM hits; UPDATE mode SET mode = 'ok', remaining = 0");
    out(200, ['ok' => true]);
}
if ($path === '/_sim/stats') {
    // Peak concurrency: replay start/end events in time order.
    $events = $db->query("SELECT t, phase FROM hits WHERE path LIKE '/electricity/%' ORDER BY t")->fetchAll();
    $cur = $peak = $total = 0;
    $perSec = [];
    foreach ($events as $e) {
        if ($e['phase'] === 'start') {
            $cur++;
            $total++;
            $perSec[(int) $e['t']] = ($perSec[(int) $e['t']] ?? 0) + 1;
        } else {
            $cur--;
        }
        $peak = max($peak, $cur);
    }
    out(200, ['requests' => $total, 'peak_concurrent' => $peak, 'peak_per_second' => $perSec ? max($perSec) : 0]);
}

// ------------------------------------------------------------------ vending API
$auth = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
if (!str_starts_with($auth, 'Basic ')) {
    out(401, ['code' => '11', 'response' => 'Failure', 'message' => 'Authorization header missing', 'status' => 401]);
}

hit($db, $path, 'start');
register_shutdown_function(fn () => hit($db, $path, 'end'));
usleep(300_000); // typical upstream processing time

$id = (string) ($body['clientSaleId'] ?? '');
$meter = (string) ($body['meterNumber'] ?? '');
$amount = (float) ($body['transactionAmount'] ?? 0);

if ($path === '/electricity/trialvend') {
    if (!isset(METERS[$meter])) {
        out(400, ['code' => '108', 'response' => 'Failure', 'message' => 'Meter not found', 'clientSaleId' => $id, 'status' => 400]);
    }
    if ($amount < 10) {
        out(400, ['code' => '28', 'response' => 'Failure', 'message' => 'Amount out of allowed range', 'status' => 400]);
    }
    out(200, ['code' => '0', 'clientSaleId' => $id, 'response' => 'Successful',
        'custVendDetail' => ['name' => METERS[$meter]['name'], 'meterNumber' => $meter, 'amtTendered' => (string) $amount],
        'transactionAmount' => (string) $amount]);
}

if ($path === '/electricity/creditvend') {
    $st = $db->prepare('SELECT 1 FROM sales WHERE client_sale_id = ?');
    $st->execute([$id]);
    if ($st->fetchColumn()) {
        out(409, ['code' => '09', 'response' => 'Duplicate', 'message' => 'Duplicate clientSaleId. Call the advice endpoint with the same clientSaleId.', 'clientSaleId' => $id, 'status' => 409]);
    }
    $db->beginTransaction();
    $m = $db->query('SELECT * FROM mode WHERE id = 1')->fetch();
    $mode = $m['remaining'] > 0 ? $m['mode'] : 'ok';
    if ($m['remaining'] > 0) {
        $db->exec('UPDATE mode SET remaining = remaining - 1 WHERE id = 1');
    }
    $db->commit();
    if (!isset(METERS[$meter]) || !empty(METERS[$meter]['blocked'])) {
        $mode = 'reject';
    }
    $now = microtime(true);
    $save = fn (string $outcome, ?array $receipt, float $resolveAt = 0) => $db->prepare('INSERT INTO sales VALUES (?,?,?,?,?,?,?)')
        ->execute([$id, $meter, $amount, $outcome, $now, $resolveAt, $receipt ? json_encode($receipt) : null]);

    switch ($mode) {
        case 'reject':
            $save('Failure', null);
            out(400, ['code' => '108', 'response' => 'Failure', 'message' => 'Meter blocked or not found', 'clientSaleId' => $id, 'status' => 400]);
        case 'down':
            out(503, []);
        case 'processing':
            $save('Pending', receipt($id, $meter, $amount), $now + (float) $m['resolve_after']);
            out(499, ['code' => '133', 'response' => 'Processing', 'message' => 'BPC has not confirmed yet. Call advice later.', 'clientSaleId' => $id]);
        case 'lost':
            $save('Successful', receipt($id, $meter, $amount));
            sleep(60); // response never arrives; client times out
        case 'lostfail':
            $save('Failure', null);
            sleep(60);
        default:
            $r = receipt($id, $meter, $amount);
            $save('Successful', $r);
            out(200, $r);
    }
}

if ($path === '/electricity/advice') {
    $st = $db->prepare('SELECT * FROM sales WHERE client_sale_id = ?');
    $st->execute([$id]);
    $s = $st->fetch();
    if (!$s) {
        out(404, ['code' => '209', 'response' => 'Failure', 'message' => 'Sale not found', 'clientSaleId' => $id, 'status' => 404]);
    }
    if ($s['outcome'] === 'Pending') {
        if (microtime(true) < (float) $s['resolve_at']) {
            out(499, ['code' => '133', 'response' => 'Processing', 'message' => 'BPC has not confirmed yet', 'clientSaleId' => $id,
                'retryAfter' => (int) ceil((float) $s['resolve_at'] - microtime(true))]);
        }
        $db->prepare("UPDATE sales SET outcome = 'Successful' WHERE client_sale_id = ?")->execute([$id]);
        $s['outcome'] = 'Successful';
    }
    if ($s['outcome'] === 'Successful') {
        out(200, json_decode($s['receipt'], true));
    }
    out(400, ['code' => '108', 'response' => 'Failure', 'message' => 'Sale failed at BPC; no token issued', 'clientSaleId' => $id, 'status' => 400]);
}

out(404, ['code' => '404', 'message' => 'Unknown endpoint']);
