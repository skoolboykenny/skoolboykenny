<?php
declare(strict_types=1);

namespace MaruVend\Teller;

use MaruVend\App;
use MaruVend\Vend\VendException;
use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App as SlimApp;

/**
 * Teller portal web: the page at /teller and its JSON API at /teller/api/*.
 * Session cookie: HttpOnly, SameSite=Strict, limited to /teller; signs out after 15 minutes idle,
 * because tills are shared. Every write must be JSON.
 */
final class TellerWeb
{
    public const IDLE_S = 900;

    public static function register(SlimApp $slim, callable $appFactory): void
    {
        $base = rtrim((string) getenv('MV_BASE_PATH'), '/');
        $json = function (Response $res, array $data, int $status = 200): Response {
            $res->getBody()->write(json_encode($data, JSON_UNESCAPED_SLASHES));
            return $res->withHeader('Content-Type', 'application/json')->withHeader('Cache-Control', 'no-store')->withStatus($status);
        };
        $session = function () use ($base): void {
            if (session_status() !== PHP_SESSION_ACTIVE) {
                session_name('maru_teller');
                session_start(['cookie_httponly' => true, 'cookie_samesite' => 'Strict', 'cookie_path' => $base . '/teller',
                    'cookie_secure' => getenv('MV_SECURE_COOKIES') === '1']);
            }
            if (!empty($_SESSION['tid']) && time() - (int) ($_SESSION['seen'] ?? 0) > self::IDLE_S) {
                $_SESSION = [];
            }
            $_SESSION['seen'] = time();
        };

        $slim->get('/teller', function (Request $r, Response $res) use ($base) {
            $res->getBody()->write(str_replace('"/teller/', '"' . $base . '/teller/', (string) file_get_contents(__DIR__ . '/../../portal/teller.html')));
            return $res->withHeader('Content-Type', 'text/html; charset=utf-8')->withHeader('X-Frame-Options', 'DENY')
                ->withHeader('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'");
        });
        foreach (['teller.css' => 'text/css', 'teller.js' => 'text/javascript', 'logo.svg' => 'image/svg+xml'] as $f => $type) {
            $slim->get("/teller/$f", function (Request $r, Response $res) use ($f, $type) {
                $res->getBody()->write((string) file_get_contents(__DIR__ . "/../../portal/$f"));
                return $res->withHeader('Content-Type', $type)->withHeader('Cache-Control', 'no-cache');
            });
        }

        $route = function (string $method, string $path, callable $fn, bool $auth = true) use ($slim, $json, $session, $appFactory) {
            $slim->map([$method], "/teller/api$path", function (Request $req, Response $res, array $args) use ($fn, $auth, $json, $session, $appFactory, $method) {
                $session();
                if ($method !== 'GET' && !str_starts_with($req->getHeaderLine('Content-Type'), 'application/json')) {
                    return $json($res, ['error' => 'BAD_REQUEST', 'message' => 'Send JSON'], 415);
                }
                $tid = (int) ($_SESSION['tid'] ?? 0);
                if ($auth && !$tid) {
                    return $json($res, ['error' => 'UNAUTHORISED', 'message' => 'Please sign in.'], 401);
                }
                /** @var App $app */
                $app = $appFactory($req->getServerParams()['REMOTE_ADDR'] ?? null);
                $body = json_decode((string) $req->getBody(), true);
                try {
                    return $json($res, $fn(new Teller($app), $tid, is_array($body) ? $body : [], $args));
                } catch (VendException $e) {
                    return $json($res, ['error' => $e->errorCode, 'message' => $e->getMessage()], $e->httpStatus);
                } catch (\Throwable $e) {
                    error_log('[teller] ' . $e);
                    return $json($res, ['error' => 'INTERNAL', 'message' => 'Something went wrong. Please try again.'], 500);
                }
            });
        };
        $s = fn (array $b, string $k) => (string) ($b[$k] ?? '');

        $route('POST', '/login', function (Teller $t, $tid, $b) use ($s) {
            $id = $t->login($s($b, 'username'), $s($b, 'pin'));
            session_regenerate_id(true);
            $_SESSION['tid'] = $id;
            $_SESSION['seen'] = time();
            return $t->me($id) + ['test' => $t->testMode()];
        }, false);
        $route('POST', '/logout', function () { $_SESSION = []; session_destroy(); return ['ok' => true]; }, false);
        $route('GET', '/me', fn (Teller $t, $tid) => $t->me($tid) + ['test' => $t->testMode()]);
        $route('POST', '/pin', function (Teller $t, $tid, $b) use ($s) { $t->changeOwnPin($tid, $s($b, 'current'), $s($b, 'pin')); return ['ok' => true]; });

        $route('POST', '/quote', fn (Teller $t, $tid, $b) => $t->quote($tid, $s($b, 'meter'), (float) ($b['amount'] ?? 0), $s($b, 'idempotency_key'), $s($b, 'msisdn')));
        $route('POST', '/sales/{id:\d+}/sell', fn (Teller $t, $tid, $b, $a) => $t->sell($tid, (int) $a['id']));
        $route('GET', '/sales/{id:\d+}', fn (Teller $t, $tid, $b, $a) => $t->status($tid, (int) $a['id']));
        $route('POST', '/sales/{id:\d+}/customer', fn (Teller $t, $tid, $b, $a) => $t->linkCustomer($tid, (int) $a['id'], $s($b, 'email')));
        $route('POST', '/reprint', fn (Teller $t, $tid, $b) => $t->reprint($tid, $s($b, 'query')));
        $route('GET', '/day', fn (Teller $t, $tid) => $t->day($tid));
        $route('GET', '/outlet', fn (Teller $t, $tid) => $t->day($tid, true));

        $route('GET', '/tellers', fn (Teller $t, $tid) => $t->tellers($tid));
        $route('POST', '/tellers', fn (Teller $t, $tid, $b) => $t->addTeller($tid, $s($b, 'username'), $s($b, 'name'), $s($b, 'pin'), $s($b, 'role')));
        $route('PUT', '/tellers/{id:\d+}', fn (Teller $t, $tid, $b, $a) => $t->updateTeller($tid, (int) $a['id'], $b));
    }
}
