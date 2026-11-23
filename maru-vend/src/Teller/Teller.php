<?php
declare(strict_types=1);

namespace MaruVend\Teller;

use MaruVend\Api\ApiApp;
use MaruVend\App;
use MaruVend\Portal\Accounts;
use MaruVend\Portal\Portal;
use MaruVend\Vend\SaleState;
use MaruVend\Vend\VendException;
use PDO;

/**
 * Teller portal: a cashier at a Maru Quick outlet sells prepaid electricity for cash.
 *
 * Each teller belongs to an outlet (merchant) and sells through that outlet's POS channel, so every
 * sale is covered by the outlet's float and goes through the same Maru Vend flow and checks as any
 * other sale. A sale can be attached to the customer's Maru Power account by email, which adds the
 * meter to that account.
 *
 * Roles: teller (sell, reprint, own shift) and manager (also: tellers of the outlet, outlet's day).
 */
final class Teller
{
    public const MAX_FAILED_LOGINS = 5;
    public const LOCK_MINUTES = 15;

    public function __construct(private App $app) {}

    private function pdo(): PDO
    {
        return $this->app->pdo;
    }

    private function one(string $sql, array $p = []): ?array
    {
        $st = $this->pdo()->prepare($sql);
        $st->execute($p);
        return $st->fetch() ?: null;
    }

    private function all(string $sql, array $p = []): array
    {
        $st = $this->pdo()->prepare($sql);
        $st->execute($p);
        return $st->fetchAll();
    }

    private function audit(array $t, string $action, ?string $id = null, ?string $new = null): void
    {
        $this->app->audit->record('teller:' . $t['username'], $t['role'], $action, 'vend_sales', $id, null, $new);
    }

    // ------------------------------------------------------------------ sign-in

    public function login(string $username, string $pin): int
    {
        $username = strtolower(trim($username));
        $t = $this->one('SELECT * FROM tellers WHERE username = ?', [$username]);
        if ($t && $t['locked_until'] !== null && strtotime((string) $t['locked_until']) > time()) {
            throw new VendException('LOCKED', 'Too many wrong PINs. Try again in ' . self::LOCK_MINUTES . ' minutes, or ask your manager.', 429);
        }
        $ok = $t && (int) $t['active'] === 1 && password_verify($pin, $t['pin_hash']);
        if (!$ok) {
            if ($t) {
                // MySQL applies SET left to right: failed_logins is already increased when the IF runs.
                $this->pdo()->prepare('UPDATE tellers SET failed_logins = failed_logins + 1,
                    locked_until = IF(failed_logins >= ?, NOW(6) + INTERVAL ? MINUTE, locked_until) WHERE id = ?')
                    ->execute([self::MAX_FAILED_LOGINS, self::LOCK_MINUTES, $t['id']]);
            }
            $this->app->audit->record('teller:' . ($t['username'] ?? $username), 'teller', 'teller.login_failed', 'tellers', $t ? (string) $t['id'] : null);
            usleep(400_000);
            throw new VendException('BAD_LOGIN', 'Wrong username or PIN.', 401);
        }
        $this->pdo()->prepare('UPDATE tellers SET failed_logins = 0, locked_until = NULL, last_login_at = NOW(6) WHERE id = ?')->execute([$t['id']]);
        $this->app->audit->record('teller:' . $t['username'], $t['role'], 'teller.login', 'tellers', (string) $t['id']);
        return (int) $t['id'];
    }

    public function me(int $tid): array
    {
        $t = $this->one('SELECT t.id, t.username, t.name, t.role, t.merchant_id, m.name outlet, m.code outlet_code
            FROM tellers t JOIN merchants m ON m.id = t.merchant_id WHERE t.id = ? AND t.active = 1', [$tid]);
        if (!$t) {
            throw new VendException('UNAUTHORISED', 'Please sign in.', 401);
        }
        return $t;
    }

    /** True while tokens come from the built-in test source. */
    public function testMode(): bool
    {
        return $this->app->settings->get('provider') === 'test';
    }

    private function channel(array $t): array
    {
        $c = $this->one("SELECT * FROM channels WHERE merchant_id = ? AND type = 'POS' AND active = 1 ORDER BY id LIMIT 1", [$t['merchant_id']]);
        if (!$c) {
            throw new VendException('NOT_CONFIGURED', 'This outlet has no till set up yet. Ask your manager.', 503);
        }
        return $c;
    }

    private function saleFor(array $t, int $saleId): array
    {
        $s = $this->app->vend()->sale($saleId);
        if ((int) $s['merchant_id'] !== (int) $t['merchant_id']) {
            throw new VendException('NOT_FOUND', 'Sale not found', 404);
        }
        return $s;
    }

    private function view(array $s): array
    {
        $v = ApiApp::view($s, $this->app);
        $v['teller_id'] = isset($s['teller_id']) ? (int) $s['teller_id'] : null;
        return $v;
    }

    // ------------------------------------------------------------------ selling

    /** Step 1: check the meter. Returns the name on the meter for the teller to read back to the customer. */
    public function quote(int $tid, string $meter, float $amount, string $key, ?string $msisdn): array
    {
        $t = $this->me($tid);
        $meter = preg_replace('/\D/', '', $meter);
        $s = $this->app->vend()->quote($this->channel($t), $meter, (int) round($amount * 100),
            't' . $tid . '-' . substr($key, 0, 40), $msisdn !== null && trim($msisdn) !== '' ? $msisdn : null);
        $this->pdo()->prepare('UPDATE vend_sales SET teller_id = ? WHERE id = ? AND teller_id IS NULL')->execute([$tid, $s['id']]);
        return $this->view($this->app->vend()->sale((int) $s['id']));
    }

    /**
     * Step 2: cash received. The amount is held against the outlet's float and the token is requested
     * at once; if it is not back within this request, the queue finishes it and the till polls status.
     */
    public function sell(int $tid, int $saleId): array
    {
        $t = $this->me($tid);
        $s = $this->saleFor($t, $saleId);
        if ((int) ($s['teller_id'] ?? 0) !== $tid) {
            throw new VendException('NOT_FOUND', 'Sale not found', 404);
        }
        $this->app->vend()->accept($this->channel($t), $saleId);
        $this->audit($t, 'teller.sale', (string) $saleId, 'P' . number_format($s['amount_thebe'] / 100, 2) . ' meter ' . $s['meter_number']);
        try {
            $this->app->vend()->processVend($saleId); // usually issues the token straight away
        } catch (\Throwable $e) {
            error_log('[teller] sale ' . $saleId . ' left for the queue: ' . $e->getMessage());
        }
        return $this->view($this->app->vend()->sale($saleId));
    }

    public function status(int $tid, int $saleId): array
    {
        return $this->view($this->saleFor($this->me($tid), $saleId));
    }

    /** Free reprint of a token sold by any outlet, by receipt number or meter (latest sale). */
    public function reprint(int $tid, string $query): array
    {
        $t = $this->me($tid);
        $q = strtoupper(preg_replace('/\s+/', '', $query));
        $s = preg_match('/^\d{11,13}$/', $q) ? $this->app->vend()->reprint(null, $q) : $this->app->vend()->reprint($q, null);
        if (!$s) {
            throw new VendException('NOT_FOUND', 'No token found for that receipt number or meter.', 404);
        }
        $this->audit($t, 'teller.reprint', (string) $s['id']);
        return $this->view($s);
    }

    /**
     * Attach a completed sale to the customer's Maru Power account: the meter is added to the account
     * (unless another account already manages it) and the purchase shows in their history.
     */
    public function linkCustomer(int $tid, int $saleId, string $email): array
    {
        $t = $this->me($tid);
        $s = $this->saleFor($t, $saleId);
        if ($s['state'] !== SaleState::SUCCEEDED) {
            throw new VendException('BAD_REQUEST', 'Only a completed sale can be added to an account.');
        }
        $acc = Accounts::for($this->app);
        $u = $acc->one('SELECT id, name FROM {users} WHERE email = ?', [strtolower(trim($email))]);
        if (!$u) {
            throw new VendException('NOT_FOUND', 'No Maru Power account uses that email. The customer can sign up at maruquick.com.', 404);
        }
        $r = (new Portal($this->app))->linkFromSale((int) $u['id'], $s);
        $this->pdo()->prepare('UPDATE vend_sales SET portal_user_id = ? WHERE id = ? AND portal_user_id IS NULL')->execute([$u['id'], $saleId]);
        $this->audit($t, 'teller.link_customer', (string) $saleId, 'account ' . $u['id'] . ': ' . $r);
        $first = explode(' ', (string) $u['name'])[0];
        return ['result' => $r, 'message' => match ($r) {
            'linked' => "Meter {$s['meter_number']} added to {$first}'s Maru Power account.",
            'already' => "This meter is already on {$first}'s account; the purchase shows there.",
            default => "The purchase is linked to {$first}'s account, but this meter is managed by another account. The owner can share it.",
        }];
    }

    // ------------------------------------------------------------------ shift and outlet

    /** Today's sales: the teller's own, or the whole outlet for a manager (all=true). */
    public function day(int $tid, bool $all = false): array
    {
        $t = $this->me($tid);
        if ($all && $t['role'] !== 'manager') {
            throw new VendException('FORBIDDEN', 'Managers only.', 403);
        }
        $where = $all ? 's.merchant_id = ?' : 's.teller_id = ?';
        $rows = $this->all("SELECT s.id, s.receipt_no, s.meter_number, s.customer_name, s.amount_thebe, s.state, s.created_at,
                tl.username teller, t.kwh FROM vend_sales s LEFT JOIN tellers tl ON tl.id = s.teller_id LEFT JOIN vend_tokens t ON t.sale_id = s.id
            WHERE $where AND s.created_at >= CURDATE() AND s.state NOT IN ('QUOTED','EXPIRED') ORDER BY s.id DESC", [$all ? $t['merchant_id'] : $tid]);
        $sum = fn (array $states) => array_sum(array_map(fn ($r) => in_array($r['state'], $states, true) ? (int) $r['amount_thebe'] : 0, $rows));
        $float = $this->app->float()->position();
        return [
            'sales' => $rows,
            'count' => count(array_filter($rows, fn ($r) => $r['state'] === SaleState::SUCCEEDED)),
            'cash_thebe' => $sum([SaleState::SUCCEEDED]),
            'pending_thebe' => $sum([SaleState::RESERVED, SaleState::SUBMITTED, SaleState::UNKNOWN, SaleState::MANUAL_REVIEW]),
            'failed_count' => count(array_filter($rows, fn ($r) => $r['state'] === SaleState::FAILED)),
            'float_available_thebe' => $t['role'] === 'manager' ? (int) $float['available'] : null,
        ];
    }

    private function manager(int $tid): array
    {
        $t = $this->me($tid);
        if ($t['role'] !== 'manager') {
            throw new VendException('FORBIDDEN', 'Managers only.', 403);
        }
        return $t;
    }

    public function tellers(int $tid): array
    {
        $m = $this->manager($tid);
        return $this->all('SELECT id, username, name, role, active, last_login_at, (locked_until > NOW(6)) locked FROM tellers WHERE merchant_id = ? ORDER BY active DESC, name', [$m['merchant_id']]);
    }

    public static function checkPin(string $pin): void
    {
        if (!preg_match('/^\d{4,8}$/', $pin) || preg_match('/^(\d)\1+$/', $pin) || in_array($pin, ['1234', '12345', '123456', '0123', '4321'], true)) {
            throw new VendException('BAD_REQUEST', 'PIN must be 4 to 8 digits and not easy to guess (not 1234 or 1111).');
        }
    }

    public function addTeller(int $tid, string $username, string $name, string $pin, string $role): array
    {
        $m = $this->manager($tid);
        $username = strtolower(trim($username));
        if (!preg_match('/^[a-z0-9._-]{3,40}$/', $username) || trim($name) === '') {
            throw new VendException('BAD_REQUEST', 'Enter a name and a username of 3 to 40 letters or numbers.');
        }
        self::checkPin($pin);
        if ($this->one('SELECT 1 FROM tellers WHERE username = ?', [$username])) {
            throw new VendException('EXISTS', 'That username is taken.', 409);
        }
        $this->pdo()->prepare('INSERT INTO tellers (merchant_id, username, name, role, pin_hash) VALUES (?,?,?,?,?)')
            ->execute([$m['merchant_id'], $username, mb_substr(trim($name), 0, 120), $role === 'manager' ? 'manager' : 'teller', password_hash($pin, PASSWORD_DEFAULT)]);
        $this->app->audit->record('teller:' . $m['username'], 'manager', 'teller.added', 'tellers', $username);
        return $this->tellers($tid);
    }

    public function updateTeller(int $tid, int $id, array $b): array
    {
        $m = $this->manager($tid);
        $x = $this->one('SELECT * FROM tellers WHERE id = ? AND merchant_id = ?', [$id, $m['merchant_id']]);
        if (!$x) {
            throw new VendException('NOT_FOUND', 'Teller not found', 404);
        }
        if (isset($b['active'])) {
            if ($id === $tid && !$b['active']) {
                throw new VendException('BAD_REQUEST', 'You cannot turn off your own login.');
            }
            $this->pdo()->prepare('UPDATE tellers SET active = ? WHERE id = ?')->execute([$b['active'] ? 1 : 0, $id]);
        }
        if (!empty($b['pin'])) {
            self::checkPin((string) $b['pin']);
            $this->pdo()->prepare('UPDATE tellers SET pin_hash = ?, failed_logins = 0, locked_until = NULL WHERE id = ?')
                ->execute([password_hash((string) $b['pin'], PASSWORD_DEFAULT), $id]);
        }
        $this->app->audit->record('teller:' . $m['username'], 'manager', 'teller.updated', 'tellers', $x['username'],
            null, json_encode(['active' => $b['active'] ?? null, 'pin_reset' => !empty($b['pin'])]));
        return $this->tellers($tid);
    }

    public function changeOwnPin(int $tid, string $current, string $new): void
    {
        $t = $this->one('SELECT * FROM tellers WHERE id = ?', [$tid]);
        if (!$t || !password_verify($current, $t['pin_hash'])) {
            throw new VendException('BAD_LOGIN', 'Current PIN is wrong.', 401);
        }
        self::checkPin($new);
        $this->pdo()->prepare('UPDATE tellers SET pin_hash = ? WHERE id = ?')->execute([password_hash($new, PASSWORD_DEFAULT), $tid]);
        $this->app->audit->record('teller:' . $t['username'], $t['role'], 'teller.pin_changed', 'tellers', (string) $tid);
    }
}
