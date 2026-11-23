<?php
declare(strict_types=1);

namespace MaruVend\Dashboard;

use MaruVend\App;
use MaruVend\Export\EncryptedExport;
use MaruVend\Reports\Reports;
use MaruVend\Support\Totp;
use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App as SlimApp;

/**
 * Read-only BPC dashboard (Scope 3f) and back-office views. Login needs password + TOTP code.
 * bpc_viewer users can see sales, queue, float, coverage, the audit trail and download reports
 * (encrypted to BPC's key); they cannot change anything.
 */
final class Dashboard
{
    public static function register(SlimApp $slim, callable $appFactory): void
    {
        $page = function (Response $res, string $title, string $body, ?array $user = null): Response {
            $nav = $user ? '<nav><a href="/bpc">Overview</a><a href="/bpc/classic">Classic</a><a href="/bpc/sales">Sales</a><a href="/bpc/queue">Queue</a>'
                . '<a href="/bpc/audit">Audit trail</a><a href="/bpc/reports">Reports</a>'
                . '<span class="who">' . h($user['username']) . ' (' . h($user['role']) . ') <a href="/bpc/logout">Log out</a></span></nav>' : '';
            $res->getBody()->write('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                . '<title>Maru Vend · ' . h($title) . '</title><style>' . self::CSS . '</style></head><body>'
                . '<header><b>Maru Vend</b> <span>BPC dashboard</span></header>' . $nav . '<main><h1>' . h($title) . '</h1>' . $body . '</main></body></html>');
            return $res->withHeader('Content-Type', 'text/html; charset=utf-8')
                ->withHeader('X-Frame-Options', 'DENY')->withHeader('Content-Security-Policy', "default-src 'self'; style-src 'unsafe-inline'");
        };

        $user = function (Request $req) {
            if (session_status() !== PHP_SESSION_ACTIVE) {
                session_start(['cookie_httponly' => true, 'cookie_samesite' => 'Strict']);
            }
            return $_SESSION['mv_user'] ?? null;
        };
        $guard = fn (callable $fn) => function (Request $req, Response $res, array $args) use ($fn, $user, $appFactory) {
            $u = $user($req);
            if (!$u) {
                return $res->withHeader('Location', '/bpc/login')->withStatus(302);
            }
            return $fn($req, $res, $args, $u, $appFactory($req->getServerParams()['REMOTE_ADDR'] ?? null));
        };

        $slim->get('/bpc/login', fn (Request $r, Response $res) => $page($res, 'Sign in', self::loginForm()));
        $slim->post('/bpc/login', function (Request $r, Response $res) use ($page, $user, $appFactory) {
            $user($r);
            $b = (array) $r->getParsedBody();
            /** @var App $app */
            $app = $appFactory($r->getServerParams()['REMOTE_ADDR'] ?? null);
            $st = $app->pdo->prepare('SELECT * FROM users WHERE username = ? AND active = 1');
            $st->execute([(string) ($b['username'] ?? '')]);
            $u = $st->fetch();
            $ok = $u && password_verify((string) ($b['password'] ?? ''), $u['password_hash']) && Totp::verify($u['totp_secret'], (string) ($b['code'] ?? ''));
            $app->audit->record((string) ($b['username'] ?? '?'), $u['role'] ?? '-', $ok ? 'login.success' : 'login.failure', 'users', isset($u['id']) ? (string) $u['id'] : null);
            if (!$ok) {
                return $page($res, 'Sign in', '<p class="err">Sign-in failed. Check your password and authenticator code.</p>' . self::loginForm());
            }
            session_regenerate_id(true);
            $_SESSION['mv_user'] = ['id' => $u['id'], 'username' => $u['username'], 'role' => $u['role']];
            return $res->withHeader('Location', '/bpc')->withStatus(302);
        });
        $slim->get('/bpc/logout', function (Request $r, Response $res) use ($user) {
            $user($r);
            $_SESSION = [];
            session_destroy();
            return $res->withHeader('Location', '/bpc/login')->withStatus(302);
        });

        // Operations dashboard (live; figures from /bpc/api/overview).
        $slim->get('/bpc', $guard(function ($r, Response $res, $a, $u, App $app) {
            $res->getBody()->write((string) file_get_contents(__DIR__ . '/ops.html'));
            return $res->withHeader('Content-Type', 'text/html; charset=utf-8')->withHeader('X-Frame-Options', 'DENY')
                ->withHeader('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                    . "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
                    . "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
                ->withHeader('Cache-Control', 'no-store');
        }));
        $slim->get('/bpc/api/overview', function (Request $r, Response $res) use ($user, $appFactory) {
            $u = $user($r);
            if (!$u) {
                return $res->withStatus(401);
            }
            session_write_close(); // polling must not hold the session lock
            $res->getBody()->write(json_encode(OpsOverview::build($appFactory($r->getServerParams()['REMOTE_ADDR'] ?? null), $u), JSON_THROW_ON_ERROR));
            return $res->withHeader('Content-Type', 'application/json')->withHeader('Cache-Control', 'no-store');
        });

        // The previous plain overview, kept for comparison.
        $slim->get('/bpc/classic', $guard(function ($r, $res, $a, $u, App $app) use ($page) {
            $pdo = $app->pdo;
            $today = $pdo->query("SELECT COUNT(*) n, COALESCE(SUM(amount_thebe),0) v FROM vend_sales WHERE state='SUCCEEDED' AND resolved_at >= CURDATE()")->fetch();
            $states = $pdo->query("SELECT state, COUNT(*) n FROM vend_sales WHERE created_at >= CURDATE() GROUP BY state")->fetchAll(\PDO::FETCH_KEY_PAIR);
            $byCh = $pdo->query("SELECT c.type, COUNT(*) n, SUM(s.amount_thebe) v FROM vend_sales s JOIN channels c ON c.id=s.channel_id
                WHERE s.state='SUCCEEDED' AND s.resolved_at >= CURDATE() GROUP BY c.type")->fetchAll();
            $f = $app->float()->position();
            $alert = $app->float()->belowAlert($app->settings->int('float_alert_pct'));
            $queue = (int) $pdo->query('SELECT COUNT(*) FROM queue_jobs WHERE done = 0')->fetchColumn();
            $areas = $pdo->query("SELECT COUNT(*) total, SUM(status='live') live FROM designated_areas")->fetch();
            $pct = $areas['total'] ? round(100 * $areas['live'] / $areas['total']) : 0;
            $body = '<div class="cards">'
                . card('Tokens sold today', number_format((int) $today['n'])) . card('Value today', 'P' . money($today['v']))
                . card('Float available', 'P' . money($f['available']), $alert ? 'Below alert level' : null)
                . card('Held for sales in progress', 'P' . money($f['reserved']))
                . card('Sales in queue', (string) $queue)
                . card('Awaiting BPC confirmation', (string) (($states['UNKNOWN'] ?? 0) + ($states['MANUAL_REVIEW'] ?? 0)))
                . card('Designated areas live', "$pct% ({$areas['live']} of {$areas['total']})", 'Targets: 80% in 3 months, 100% in 6')
                . '</div><h2>Today by channel</h2>' . table(['Channel', 'Tokens', 'Value (P)'], array_map(fn ($c) => [$c['type'], $c['n'], money($c['v'])], $byCh))
                . '<h2>Today by status</h2>' . table(['Status', 'Sales'], array_map(null, array_keys($states), array_values($states)));
            return $page($res, 'Overview', $body, $u);
        }));

        $slim->get('/bpc/sales', $guard(function (Request $r, $res, $a, $u, App $app) use ($page) {
            $q = $r->getQueryParams();
            $sql = 'SELECT s.id, s.receipt_no, s.created_at, c.type, s.meter_number, s.customer_name, s.amount_thebe, s.state, s.fault_code
                FROM vend_sales s JOIN channels c ON c.id = s.channel_id WHERE 1=1';
            $p = [];
            if (!empty($q['meter'])) { $sql .= ' AND s.meter_number = ?'; $p[] = $q['meter']; }
            if (!empty($q['state'])) { $sql .= ' AND s.state = ?'; $p[] = $q['state']; }
            $st = $app->pdo->prepare($sql . ' ORDER BY s.id DESC LIMIT 200');
            $st->execute($p);
            $rows = array_map(fn ($s) => ['<a href="/bpc/sales/' . (int) $s['id'] . '">' . h($s['receipt_no']) . '</a>', h(substr($s['created_at'], 0, 19)), h($s['type']),
                h($s['meter_number']), h((string) $s['customer_name']), money($s['amount_thebe']), h($s['state']), h((string) $s['fault_code'])], $st->fetchAll());
            $form = '<form class="inline" method="get"><input name="meter" placeholder="Meter number" value="' . h($q['meter'] ?? '') . '">'
                . '<input name="state" placeholder="Status" value="' . h($q['state'] ?? '') . '"><button>Filter</button></form>';
            return $page($res, 'Sales', $form . table(['Receipt', 'Created', 'Channel', 'Meter', 'Customer', 'Amount (P)', 'Status', 'Fault'], $rows, true), $u);
        }));

        $slim->get('/bpc/sales/{id}', $guard(function ($r, $res, $a, $u, App $app) use ($page) {
            $s = $app->vend()->sale((int) $a['id']);
            $ev = $app->pdo->prepare('SELECT at, from_state, to_state, cause, actor, fault_code FROM sale_events WHERE sale_id = ? ORDER BY seq');
            $ev->execute([(int) $a['id']]);
            $rows = array_map(fn ($e) => [h(substr($e['at'], 0, 23)), h((string) $e['from_state']), h($e['to_state']), h($e['cause']), h($e['actor']), h((string) $e['fault_code'])], $ev->fetchAll());
            $receipt = $s['token'] ? table(['Field', 'Value'], [
                ['BPC VAT number', h($app->settings->get('bpc_vat_no'))], ['Date', h(substr((string) $s['issued_at'], 0, 19))], ['Receipt number', h($s['receipt_no'])],
                ['Tariff index', h((string) $s['tariff_index'])], ['Meter number', h($s['meter_number'])], ['Customer name', h((string) $s['customer_name'])],
                ['Transaction amount', 'P' . money($s['amount_thebe'])], ['kWh', h((string) $s['kwh'])], ['Cost of units', 'P' . money($s['cost_units_thebe'])],
                ['Fixed charge', 'P' . money($s['fixed_charge_thebe'])], ['Government levy', 'P' . money($s['gov_levy_thebe'])], ['VAT', 'P' . money($s['vat_thebe'])],
                ['Token', h(trim(chunk_split($s['token'], 4, ' ')))],
            ], true) : '<p>No token issued.</p>';
            return $page($res, 'Sale ' . $s['receipt_no'], '<h2>Receipt</h2>' . $receipt . '<h2>History</h2>' . table(['Time', 'From', 'To', 'Reason', 'By', 'Fault'], $rows, true), $u);
        }));

        $slim->get('/bpc/queue', $guard(function ($r, $res, $a, $u, App $app) use ($page) {
            $rows = $app->pdo->query('SELECT q.id, s.receipt_no, q.action, q.attempts, q.next_run_at, q.locked_by, s.state FROM queue_jobs q
                JOIN vend_sales s ON s.id = q.sale_id WHERE q.done = 0 ORDER BY q.next_run_at LIMIT 200')->fetchAll(\PDO::FETCH_NUM);
            $info = '<p>Every sale passes through this queue. Only the queue workers submit to BPC, at no more than <b>'
                . $app->settings->int('rate_per_s') . ' requests per second</b>. BPC timeout: <b>' . $app->settings->int('bpc_timeout_s')
                . ' s</b>; worker timeout ' . $app->settings->workerTimeout() . ' s.</p>';
            return $page($res, 'Queue', $info . table(['Job', 'Receipt', 'Action', 'Attempts', 'Next run', 'Worker', 'Sale status'], array_map(fn ($x) => array_map(__NAMESPACE__ . '\h', array_map('strval', $x)), $rows), true), $u);
        }));

        $slim->get('/bpc/audit', $guard(function (Request $r, $res, $a, $u, App $app) use ($page) {
            $check = '';
            if (isset($r->getQueryParams()['verify'])) {
                $v = $app->audit->verify();
                $check = $v['ok']
                    ? "<p class=\"ok\">Audit trail intact: {$v['rows']} entries and {$v['anchors']} signed checkpoints verified.</p>"
                    : '<p class="err">Audit trail tampering detected:</p><ul>' . implode('', array_map(fn ($p) => '<li>' . h($p) . '</li>', $v['problems'])) . '</ul>';
                $app->audit->record($u['username'], $u['role'], 'audit.verify', 'audit_log', null, null, $v['ok'] ? 'intact' : 'TAMPERED');
            }
            $rows = $app->pdo->query('SELECT id, created_at, actor, role, action, entity, entity_id, old_value, new_value, ip, LEFT(hash, 12) FROM audit_log ORDER BY id DESC LIMIT 300')->fetchAll(\PDO::FETCH_NUM);
            return $page($res, 'Audit trail', '<p><a class="btn" href="/bpc/audit?verify=1">Verify integrity now</a></p>' . $check
                . table(['#', 'Time', 'Who', 'Role', 'Action', 'Entity', 'Id', 'Old', 'New', 'IP', 'Hash'], array_map(fn ($x) => array_map(fn ($v) => h((string) $v), $x), $rows), true), $u);
        }));

        $slim->get('/bpc/reports', $guard(function (Request $r, $res, $a, $u, App $app) use ($page) {
            $from = date('Y-m-01');
            $to = date('Y-m-d', strtotime('+1 day'));
            $form = '<form method="get" action="/bpc/reports/download"><label>Report <select name="type">'
                . '<option value="sales">Sales (Annexure 3)</option><option value="pit">Transactions as at a point in time</option>'
                . '<option value="invoice">Service fee invoice</option><option value="recon">Reconciliation</option></select></label>'
                . '<label>From <input type="date" name="from" value="' . $from . '"></label><label>To <input type="date" name="to" value="' . $to . '"></label>'
                . '<label>As at <input type="datetime-local" name="at"></label>'
                . '<label>Channel <select name="channel"><option value="">All</option><option>POS</option><option>APP</option><option>WEB</option><option>USSD</option></select></label>'
                . '<label>Meter <input name="meter"></label><button>Download encrypted file</button></form>'
                . '<p>Files are encrypted with BPC\'s public key and can only be opened by BPC. Every download is recorded in the audit trail.</p>';
            $preview = table(array_keys($app->reports()->reconciliation($from, $to)), [array_map(__NAMESPACE__ . '\h', array_values($app->reports()->reconciliation($from, $to)))]);
            return $page($res, 'Reports', $form . '<h2>This month</h2>' . $preview, $u);
        }));

        $slim->get('/bpc/reports/download', $guard(function (Request $r, Response $res, $a, $u, App $app) {
            $q = $r->getQueryParams();
            $from = $q['from'] ?? date('Y-m-d');
            $to = $q['to'] ?? date('Y-m-d', strtotime('+1 day'));
            $rp = $app->reports();
            $rows = match ($q['type'] ?? 'sales') {
                'pit' => $rp->pointInTime(str_replace('T', ' ', $q['at'] ?: date('Y-m-d H:i:s'))),
                'invoice' => $rp->serviceFeeInvoice($from, $to),
                'recon' => $rp->reconciliation($from, $to),
                default => $rp->sales($from, $to, ['channel' => $q['channel'] ?? null, 'meter' => $q['meter'] ?? null]),
            };
            $name = 'maruvend-' . ($q['type'] ?? 'sales') . '-' . date('Ymd-His') . '.csv.gpg';
            $out = sys_get_temp_dir() . '/' . $name;
            EncryptedExport::fromEnv($app->audit)->export($name, Reports::toCsv($rows), $out, $u['username']);
            $res->getBody()->write((string) file_get_contents($out));
            unlink($out);
            return $res->withHeader('Content-Type', 'application/pgp-encrypted')->withHeader('Content-Disposition', "attachment; filename=\"$name\"");
        }));
    }

    private static function loginForm(): string
    {
        return '<form method="post" action="/bpc/login" class="login"><label>Username <input name="username" autocomplete="username" required></label>'
            . '<label>Password <input type="password" name="password" autocomplete="current-password" required></label>'
            . '<label>Authenticator code <input name="code" inputmode="numeric" pattern="\d{6}" autocomplete="one-time-code" required></label>'
            . '<button>Sign in</button></form>';
    }

    private const CSS = <<<'CSS'
:root{--bg:#fff;--fg:#111;--mut:#555;--line:#e5e7eb;--acc:#FDE047;--acc2:#facc15;--card:#fafaf9;--err:#b91c1c;--ok:#15803d}
@media (prefers-color-scheme:dark){:root{--bg:#121212;--fg:#eee;--mut:#aaa;--line:#333;--card:#1c1c1c;--acc:#facc15;--acc2:#eab308}}
*{box-sizing:border-box}body{margin:0;font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--fg)}
header{background:var(--acc);color:#111;padding:12px 16px;font-size:18px}header span{font-size:14px;margin-left:8px}
nav{display:flex;flex-wrap:wrap;gap:4px 16px;padding:10px 16px;border-bottom:1px solid var(--line)}nav a{color:var(--fg)}.who{margin-left:auto;color:var(--mut)}
main{padding:16px;max-width:1200px;margin:auto}h1{font-size:22px;margin:4px 0 16px}h2{font-size:17px;margin:24px 0 8px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}.card{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--acc2);padding:12px;border-radius:6px}
.card .v{font-size:22px;font-weight:600}.card .l{color:var(--mut);font-size:13px}.card .n{color:var(--err);font-size:12px}
.tw{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}th{background:var(--card)}
form{display:flex;flex-wrap:wrap;gap:10px;align-items:end;margin-bottom:12px}form.login{flex-direction:column;align-items:stretch;max-width:320px}label{display:flex;flex-direction:column;font-size:13px;color:var(--mut);gap:4px}
input,select,button{font:inherit;padding:7px 9px;border:1px solid var(--line);border-radius:5px;background:var(--bg);color:var(--fg)}button,.btn{background:var(--acc);color:#111;border:0;font-weight:600;cursor:pointer;padding:8px 14px;border-radius:5px;text-decoration:none;display:inline-block}
.err{color:var(--err)}.ok{color:var(--ok);font-weight:600}
CSS;
}

function h(string $s): string
{
    return htmlspecialchars($s, ENT_QUOTES, 'UTF-8');
}

function money(int|string|null $t): string
{
    return number_format(((int) $t) / 100, 2);
}

function card(string $label, string $value, ?string $note = null): string
{
    return '<div class="card"><div class="l">' . h($label) . '</div><div class="v">' . h($value) . '</div>' . ($note ? '<div class="n">' . h($note) . '</div>' : '') . '</div>';
}

/** @param list<list<string>> $rows values must already be escaped when $raw is true */
function table(array $head, array $rows, bool $raw = false): string
{
    $th = implode('', array_map(fn ($x) => '<th>' . h((string) $x) . '</th>', $head));
    $tr = implode('', array_map(fn ($r) => '<tr>' . implode('', array_map(fn ($c) => '<td>' . ($raw ? (string) $c : h((string) $c)) . '</td>', $r)) . '</tr>', $rows));
    return '<div class="tw"><table><thead><tr>' . $th . '</tr></thead><tbody>' . ($tr ?: '<tr><td colspan="' . count($head) . '">None</td></tr>') . '</tbody></table></div>';
}
