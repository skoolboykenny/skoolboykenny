<?php
declare(strict_types=1);

namespace MaruVend\Portal;

use MaruVend\App;
use MaruVend\Vend\VendException;
use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App as SlimApp;

/**
 * Maru Power web: the page at /power and its JSON API at /power/api/*.
 * Session cookie is HttpOnly + SameSite=Strict, and every write must be JSON, so other sites cannot post to it.
 */
final class PortalWeb
{
    public static function register(SlimApp $slim, callable $appFactory): void
    {
        $json = function (Response $res, array $data, int $status = 200): Response {
            $res->getBody()->write(json_encode($data, JSON_UNESCAPED_SLASHES));
            return $res->withHeader('Content-Type', 'application/json')->withHeader('Cache-Control', 'no-store')->withStatus($status);
        };
        $session = function (): void {
            if (session_status() !== PHP_SESSION_ACTIVE) {
                session_name('maru_power');
                session_start(['cookie_httponly' => true, 'cookie_samesite' => 'Strict', 'cookie_path' => '/power',
                    'cookie_secure' => getenv('MV_SECURE_COOKIES') === '1']);
            }
        };

        $slim->get('/power', function (Request $r, Response $res) {
            $res->getBody()->write((string) file_get_contents(__DIR__ . '/../../portal/index.html'));
            return $res->withHeader('Content-Type', 'text/html; charset=utf-8')->withHeader('X-Frame-Options', 'DENY')
                ->withHeader('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'");
        });
        foreach (['power.css' => 'text/css', 'power.js' => 'text/javascript', 'logo.svg' => 'image/svg+xml'] as $f => $type) {
            $slim->get("/power/$f", function (Request $r, Response $res) use ($f, $type) {
                $res->getBody()->write((string) file_get_contents(__DIR__ . "/../../portal/$f"));
                return $res->withHeader('Content-Type', $type)->withHeader('Cache-Control', 'no-cache');
            });
        }

        $route = function (string $method, string $path, callable $fn, bool $auth = true) use ($slim, $json, $session, $appFactory) {
            $slim->map([$method], "/power/api$path", function (Request $req, Response $res, array $args) use ($fn, $auth, $json, $session, $appFactory, $method) {
                $session();
                if ($method !== 'GET' && !str_starts_with($req->getHeaderLine('Content-Type'), 'application/json')) {
                    return $json($res, ['error' => 'BAD_REQUEST', 'message' => 'Send JSON'], 415);
                }
                $uid = (int) ($_SESSION['mp_uid'] ?? 0);
                if ($auth && !$uid) {
                    return $json($res, ['error' => 'UNAUTHORISED', 'message' => 'Please sign in.'], 401);
                }
                /** @var App $app */
                $app = $appFactory($req->getServerParams()['REMOTE_ADDR'] ?? null);
                $body = json_decode((string) $req->getBody(), true);
                try {
                    return $json($res, $fn(new Portal($app), $uid, is_array($body) ? $body : [], $args));
                } catch (VendException $e) {
                    return $json($res, ['error' => $e->errorCode, 'message' => $e->getMessage()], $e->httpStatus);
                } catch (\Throwable $e) {
                    error_log('[power] ' . $e);
                    return $json($res, ['error' => 'INTERNAL', 'message' => 'Something went wrong. Please try again.'], 500);
                }
            });
        };

        $start = function (int $uid): array {
            session_regenerate_id(true);
            $_SESSION['mp_uid'] = $uid;
            return ['ok' => true];
        };
        $s = fn (array $b, string $k) => (string) ($b[$k] ?? '');

        $route('POST', '/signup', fn (Portal $p, $u, $b) => $start($p->signup($s($b, 'name'), $s($b, 'email'), $s($b, 'password'),
            $s($b, 'account_type') ?: 'household', ['company_name' => $s($b, 'company_name'), 'company_reg' => $s($b, 'company_reg'), 'vat_no' => $s($b, 'vat_no')])), false);
        $route('POST', '/login', fn (Portal $p, $u, $b) => $start($p->login($s($b, 'email'), $s($b, 'password'))), false);
        $route('POST', '/logout', function () { $_SESSION = []; session_destroy(); return ['ok' => true]; }, false);
        $route('GET', '/me', fn (Portal $p, $u) => $p->me($u));
        $route('GET', '/dashboard', fn (Portal $p, $u) => $p->dashboard($u));
        $route('POST', '/phone', fn (Portal $p, $u, $b) => $p->requestPhoneCode($u, $s($b, 'msisdn')));
        $route('POST', '/phone/verify', fn (Portal $p, $u, $b) => $p->verifyPhone($u, $s($b, 'code')));

        $route('GET', '/meters', fn (Portal $p, $u) => $p->meters($u));
        $route('POST', '/meters/claim', fn (Portal $p, $u, $b) => $p->claimByReceipt($u, $s($b, 'receipt_no'), $s($b, 'token'), $s($b, 'label'), $s($b, 'site_type') ?: 'home'));
        $route('GET', '/meters/{m:\d{11,13}}', fn (Portal $p, $u, $b, $a) => $p->meter($u, $a['m']));
        $route('PUT', '/meters/{m:\d{11,13}}', fn (Portal $p, $u, $b, $a) => $p->updateMeter($u, $a['m'], $b));
        $route('DELETE', '/meters/{m:\d{11,13}}', function (Portal $p, $u, $b, $a) { $p->unlink($u, $a['m']); return ['ok' => true]; });
        $route('POST', '/meters/{m:\d{11,13}}/share', fn (Portal $p, $u, $b, $a) => $p->share($u, $a['m'], $s($b, 'email')));
        $route('DELETE', '/meters/{m:\d{11,13}}/share/{id:\d+}', fn (Portal $p, $u, $b, $a) => $p->unshare($u, $a['m'], (int) $a['id']));

        $route('GET', '/transactions', fn (Portal $p, $u) => $p->transactions($u, null, 200));
        $route('GET', '/transactions/{id:\d+}', fn (Portal $p, $u, $b, $a) => $p->transaction($u, (int) $a['id']));
        $route('GET', '/methods', fn () => ['methods' => \MaruVend\Channels\PaymentGateway::METHODS, 'test' => \MaruVend\Channels\PaymentGateway::testMode()], false);
        $route('POST', '/buy', fn (Portal $p, $u, $b) => $p->quote($u, $s($b, 'meter'), (float) ($b['amount'] ?? 0), $s($b, 'idempotency_key')));
        $route('POST', '/buy/{id:\d+}/pay', fn (Portal $p, $u, $b, $a) => $p->pay($u, (int) $a['id'], $s($b, 'method')));
    }
}
