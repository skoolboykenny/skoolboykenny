<?php
declare(strict_types=1);

/**
 * Maru Vend channel server: web store, Maru app (installable web app), merchant POS and USSD.
 * Holds each channel's API secret and calls the core API on behalf of browsers and phones.
 *
 *   /            web store (customers)          channel WEB, 24h
 *   /app         Maru app (installable)         channel APP, 24h
 *   /pos         merchant point of sale         channel POS
 *   /ussd        USSD aggregator callback       channel USSD, 24h
 *   /ussd-phone  USSD phone emulator            test environment only
 */

// php -S: let the built-in server return static files directly.
if (PHP_SAPI === 'cli-server' && is_file(__DIR__ . parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH))) {
    return false;
}

require __DIR__ . '/../../vendor/autoload.php';

use MaruVend\Channels\CoreClient;
use MaruVend\Channels\PaymentGateway;
use MaruVend\Channels\Ussd;
use Psr\Http\Message\ResponseInterface as Res;
use Psr\Http\Message\ServerRequestInterface as Req;
use Slim\Factory\AppFactory;

session_start(['cookie_httponly' => true, 'cookie_samesite' => 'Strict']);

$app = AppFactory::create();
$app->addBodyParsingMiddleware();

$json = function (Res $res, array $data, int $status = 200): Res {
    $res->getBody()->write(json_encode($data, JSON_UNESCAPED_SLASHES));
    return $res->withHeader('Content-Type', 'application/json')->withHeader('Cache-Control', 'no-store')->withStatus($status);
};
$page = function (Res $res, string $file): Res {
    $res->getBody()->write((string) file_get_contents(__DIR__ . '/../views/' . $file));
    return $res->withHeader('Content-Type', 'text/html; charset=utf-8')
        ->withHeader('X-Frame-Options', 'DENY')
        ->withHeader('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'");
};
$forward = fn (Res $res, array $r) => $json($res, $r[1], $r[0]);

/** Channels a request may act as. POS needs a logged-in operator. */
$channelOf = function (string $ch): ?string {
    return match ($ch) {
        'web', 'app' => $ch,
        'pos' => isset($_SESSION['pos_operator']) ? 'pos' : null,
        default => null,
    };
};
$guarded = fn (callable $fn) => function (Req $req, Res $res, array $a) use ($fn, $channelOf, $json) {
    $ch = $channelOf($a['ch']);
    if (!$ch) {
        return $json($res, ['error' => 'UNAUTHORISED', 'message' => 'Please sign in.'], 401);
    }
    return $fn($req, $res, $a, CoreClient::forChannel($ch), $ch);
};

// ---------------------------------------------------------------- pages
$app->get('/', fn (Req $r, Res $res) => $page($res, 'store.html'));
$app->get('/app', fn (Req $r, Res $res) => $page($res, 'store.html'));
$app->get('/pos', fn (Req $r, Res $res) => $page($res, 'pos.html'));
$app->get('/ussd-phone', fn (Req $r, Res $res) => getenv('MV_DEMO') === '1' ? $page($res, 'ussd.html') : $res->withStatus(404));

// ---------------------------------------------------------------- customer and POS API
$app->get('/api/config', fn (Req $r, Res $res) => $json($res, [
    'testPayments' => PaymentGateway::testMode(),
    'methods' => PaymentGateway::METHODS,
    'operator' => $_SESSION['pos_operator'] ?? null,
]));

$app->post('/api/{ch}/confirm', $guarded(function (Req $req, Res $res, array $a, CoreClient $core) use ($forward) {
    $b = (array) $req->getParsedBody();
    return $forward($res, $core->call('POST', '/v1/confirm', [
        'meter' => (string) ($b['meter'] ?? ''),
        'amount' => (float) ($b['amount'] ?? 0),
        'msisdn' => ($b['msisdn'] ?? '') !== '' ? (string) $b['msisdn'] : null,
        'idempotency_key' => substr((string) ($b['idempotency_key'] ?? ''), 0, 64),
    ]));
}));

$app->post('/api/{ch}/accept', $guarded(fn (Req $req, Res $res, array $a, CoreClient $core) =>
    $forward($res, $core->call('POST', '/v1/vend', ['sale_id' => (int) (((array) $req->getParsedBody())['sale_id'] ?? 0)]))));

$app->get('/api/{ch}/status/{id}', $guarded(fn (Req $req, Res $res, array $a, CoreClient $core) =>
    $forward($res, $core->call('GET', '/v1/vend/' . (int) $a['id']))));

$app->post('/api/{ch}/reprint', $guarded(function (Req $req, Res $res, array $a, CoreClient $core) use ($forward) {
    $b = (array) $req->getParsedBody();
    $q = !empty($b['receipt_no']) ? ['receipt_no' => (string) $b['receipt_no']] : ['meter' => preg_replace('/\D/', '', (string) ($b['meter'] ?? ''))];
    return $forward($res, $core->call('POST', '/v1/reprint', $q));
}));

// Customer pays (app and web store only; POS takes cash against the merchant float).
$app->post('/api/{ch}/pay/{id}', $guarded(function (Req $req, Res $res, array $a, CoreClient $core, string $ch) use ($json, $forward) {
    if ($ch === 'pos') {
        return $json($res, ['error' => 'BAD_REQUEST', 'message' => 'POS sales are paid in store.'], 400);
    }
    $b = (array) $req->getParsedBody();
    $method = (string) ($b['method'] ?? '');
    if (!isset(PaymentGateway::METHODS[$method])) {
        return $json($res, ['error' => 'BAD_METHOD', 'message' => 'Choose a payment method.'], 422);
    }
    [$code, $s] = $core->call('GET', '/v1/vend/' . (int) $a['id']);
    if ($code !== 200) {
        return $json($res, $s, $code);
    }
    if (!PaymentGateway::testMode()) {
        return $json($res, ['error' => 'NOT_CONFIGURED', 'message' => 'Online payments are not available yet.'], 503);
    }
    return $forward($res, PaymentGateway::confirm($ch, (int) $a['id'], 'TEST-' . strtoupper($method) . '-' . (int) $a['id']));
}));

// Production payment provider callback: verify the provider's signature, then PaymentGateway::confirm().
$app->post('/pay/callback/{provider}', fn (Req $r, Res $res) =>
    $json($res, ['error' => 'NOT_CONFIGURED', 'message' => 'Payment provider callbacks are configured after contracting.'], 501));

// ---------------------------------------------------------------- POS operator sign-in
$app->post('/api/pos/login', function (Req $req, Res $res) use ($json) {
    $b = (array) $req->getParsedBody();
    // MV_POS_OPERATORS="op1:hash,op2:hash" (password_hash of the PIN). Demo default: operator "till1", PIN 1234.
    $ops = [];
    foreach (array_filter(explode(',', getenv('MV_POS_OPERATORS') ?: 'till1:' . password_hash('1234', PASSWORD_DEFAULT))) as $pair) {
        [$id, $hash] = explode(':', $pair, 2);
        $ops[$id] = $hash;
    }
    $id = (string) ($b['operator'] ?? '');
    if (!isset($ops[$id]) || !password_verify((string) ($b['pin'] ?? ''), $ops[$id])) {
        usleep(500_000);
        return $json($res, ['error' => 'BAD_LOGIN', 'message' => 'Wrong operator or PIN.'], 401);
    }
    session_regenerate_id(true);
    $_SESSION['pos_operator'] = $id;
    return $json($res, ['operator' => $id]);
});
$app->post('/api/pos/logout', function (Req $req, Res $res) use ($json) {
    $_SESSION = [];
    session_destroy();
    return $json($res, ['ok' => true]);
});

// ---------------------------------------------------------------- USSD
$app->post('/ussd', function (Req $req, Res $res) {
    $b = (array) $req->getParsedBody();
    $reply = (new Ussd(CoreClient::forChannel('ussd')))->handle(
        (string) ($b['sessionId'] ?? ''), (string) ($b['phoneNumber'] ?? ''), (string) ($b['text'] ?? '')
    );
    $res->getBody()->write($reply);
    return $res->withHeader('Content-Type', 'text/plain; charset=utf-8');
});

// Emulator support (test environment): SMS received by a phone number.
$app->get('/api/ussd/sms', function (Req $req, Res $res) use ($forward, $json) {
    if (getenv('MV_DEMO') !== '1') {
        return $json($res, [], 404);
    }
    $m = preg_replace('/\D/', '', (string) ($req->getQueryParams()['msisdn'] ?? ''));
    return $forward($res, CoreClient::forChannel('ussd')->call('GET', '/v1/demo/sms?msisdn=' . urlencode($m)));
});

$app->run();
