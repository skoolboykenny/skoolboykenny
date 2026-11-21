<?php
declare(strict_types=1);

namespace MaruVend\Api;

use MaruVend\App;
use MaruVend\Vend\VendException;
use MaruVend\Vend\VendService;
use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Psr\Http\Server\RequestHandlerInterface as Handler;
use Slim\App as SlimApp;
use Slim\Factory\AppFactory;

/**
 * Maru Vend channel API (v1). Used by POS, app, web store and USSD. No endpoint here ever
 * calls BPC for a token: sales are queued and channels poll status.
 *
 *   POST /v1/confirm            {meter, amount, idempotency_key}  -> sale in QUOTED with customer name
 *   POST /v1/vend               {sale_id}                         -> accept; POS queued at once, others await payment
 *   POST /v1/sales/{id}/payment {payment_ref}                     -> payment confirmed; sale queued
 *   GET  /v1/vend/{id}                                            -> status; receipt and token when complete
 *   POST /v1/reprint            {receipt_no} | {meter}            -> free reprint
 *   POST /v1/confirm also takes optional msisdn: the token is then sent by SMS as well.
 *   GET  /v1/demo/sms?msisdn=   test environment only (MV_DEMO=1): SMS sent to a phone, for the USSD emulator
 */
final class ApiApp
{
    public static function create(callable $appFactory): SlimApp
    {
        $slim = AppFactory::create();
        $slim->addBodyParsingMiddleware();

        $auth = function (Request $req, Handler $h) use ($appFactory): Response {
            /** @var App $app */
            $app = $appFactory($req->getServerParams()['REMOTE_ADDR'] ?? null);
            $body = (string) $req->getBody();
            $channel = (new HmacAuth($app->pdo))->verify(
                $req->getHeaderLine('X-MV-Key'), $req->getHeaderLine('X-MV-Timestamp'), $req->getHeaderLine('X-MV-Signature'),
                $req->getMethod(), $req->getUri()->getPath(), $body
            );
            if (!$channel) {
                return self::json(new \Slim\Psr7\Response(), ['error' => 'UNAUTHORISED', 'message' => 'Invalid or missing signature'], 401);
            }
            return $h->handle($req->withAttribute('channel', $channel)->withAttribute('app', $app));
        };

        $wrap = fn (callable $fn) => function (Request $req, Response $res, array $args) use ($fn) {
            try {
                return self::json($res, $fn($req->getAttribute('app'), $req->getAttribute('channel'), (array) $req->getParsedBody(), $args));
            } catch (VendException $e) {
                return self::json($res, ['error' => $e->errorCode, 'message' => $e->getMessage()], $e->httpStatus);
            } catch (\Throwable $e) {
                error_log('[api] ' . $e);
                return self::json($res, ['error' => 'INTERNAL', 'message' => 'Unexpected error'], 500);
            }
        };

        $slim->group('/v1', function ($g) use ($wrap) {
            $g->post('/confirm', $wrap(function (App $app, array $ch, array $b) {
                $amount = (int) round(((float) ($b['amount'] ?? 0)) * 100);
                $key = (string) ($b['idempotency_key'] ?? '');
                if ($key === '' || strlen($key) > 64) {
                    throw new VendException('BAD_REQUEST', 'idempotency_key is required (max 64 characters).');
                }
                return self::view($app->vend()->quote($ch, (string) ($b['meter'] ?? ''), $amount, $key, isset($b['msisdn']) ? (string) $b['msisdn'] : null), $app);
            }));
            $g->post('/vend', $wrap(fn (App $app, array $ch, array $b) => self::view($app->vend()->accept($ch, (int) ($b['sale_id'] ?? 0)), $app)));
            $g->post('/sales/{id}/payment', $wrap(fn (App $app, array $ch, array $b, array $a) =>
                self::view($app->vend()->markPaid($ch, (int) $a['id'], (string) ($b['payment_ref'] ?? '')), $app)));
            $g->get('/vend/{id}', $wrap(fn (App $app, array $ch, array $b, array $a) => self::view($app->vend()->status($ch, (int) $a['id']), $app)));
            $g->post('/reprint', $wrap(function (App $app, array $ch, array $b) {
                $s = $app->vend()->reprint($b['receipt_no'] ?? null, $b['meter'] ?? null);
                if (!$s) {
                    throw new VendException('NOT_FOUND', 'No token found for that receipt or meter.', 404);
                }
                return self::view($s, $app);
            }));
            $g->get('/demo/sms', $wrap(function (App $app, array $ch, array $b) {
                if (\MaruVend\Config::env('MV_DEMO') !== '1') {
                    throw new VendException('NOT_FOUND', 'Not available', 404);
                }
                $m = VendService::normaliseMsisdn((string) ($_GET['msisdn'] ?? ''));
                $st = $app->pdo->prepare("SELECT body, status, created_at FROM sms_outbox WHERE msisdn = ? ORDER BY id DESC LIMIT 10");
                $st->execute([$m]);
                return ['messages' => $st->fetchAll()];
            }));
        })->add($auth);

        $slim->get('/health', fn (Request $r, Response $res) => self::json($res, ['ok' => true]));
        return $slim;
    }

    /** Public view of a sale: Annexure 1 receipt fields once a token exists. */
    public static function view(array $s, App $app): array
    {
        $p = fn ($t) => $t === null ? null : number_format(((int) $t) / 100, 2, '.', '');
        $out = [
            'sale_id' => (int) $s['id'],
            'status' => $s['state'],
            'message' => $s['message'],
            'receipt_no' => $s['receipt_no'],
            'meter_number' => $s['meter_number'],
            'customer_name' => $s['customer_name'],
            'amount' => $p($s['amount_thebe']),
            'poll_after_s' => in_array($s['state'], ['RESERVED', 'SUBMITTED', 'UNKNOWN', 'MANUAL_REVIEW'], true) ? 3 : null,
        ];
        if (!empty($s['token'])) {
            $fmt = fn ($t) => $t ? trim(chunk_split($t, 4, ' ')) : null;
            $out['receipt'] = [
                'bpc_vat_no' => $app->settings->get('bpc_vat_no'),
                'date' => substr((string) $s['issued_at'], 0, 19),
                'receipt_no' => $s['receipt_no'],
                'tariff_index' => $s['tariff_index'],
                'meter_number' => $s['meter_number'],
                'customer_name' => $s['customer_name'],
                'transaction_amount' => $p($s['amount_thebe']),
                'kwh' => number_format((float) $s['kwh'], 1, '.', ''),
                'cost_of_units' => $p($s['cost_units_thebe']),
                'fixed_charge' => $p($s['fixed_charge_thebe']),
                'government_levy' => $p($s['gov_levy_thebe']),
                'vat' => $p($s['vat_thebe']),
                'key_change_token_1' => $fmt($s['key_change_1']),
                'key_change_token_2' => $fmt($s['key_change_2']),
                'token' => $fmt($s['token']),
            ];
        }
        return $out;
    }

    private static function json(Response $res, array $data, int $status = 200): Response
    {
        $res->getBody()->write(json_encode($data, JSON_UNESCAPED_SLASHES));
        return $res->withHeader('Content-Type', 'application/json')->withStatus($status);
    }
}
