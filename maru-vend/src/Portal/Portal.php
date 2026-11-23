<?php
declare(strict_types=1);

namespace MaruVend\Portal;

use MaruVend\App;
use MaruVend\Db;
use MaruVend\Vend\SaleState;
use MaruVend\Vend\VendException;
use MaruVend\Vend\VendService;
use PDO;

/**
 * Maru Power: the customer's own view of the Maru Vend database.
 *
 * A customer links meters to their account. From then on every sale for those meters, from any
 * channel (a teller's till, USSD, the web store, the app, Maru Power itself), shows in their account
 * with its receipt, token and the checks that prove the money was received and the token issued.
 *
 * Meters are linked with proof, never by typing a number alone:
 *   - receipt: the receipt number and 20-digit token from any successful purchase on that meter;
 *   - phone:   a verified mobile number that past purchases on that meter were sent to by SMS;
 *   - shared:  the meter's owner added this account.
 */
final class Portal
{
    public const MAX_CLAIM_ATTEMPTS = 5; // per account per hour

    private Accounts $acc;

    public function __construct(private App $app, ?Accounts $accounts = null)
    {
        $this->acc = $accounts ?? Accounts::for($app);
    }

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

    // ------------------------------------------------------------------ accounts

    /**
     * Create a Maru Power account.
     * Household: one person and their home(s). Business: a company with sites and meters; needs the
     * company name and CIPA registration number (UIN), and may give a BURS VAT number.
     */
    public function signup(string $name, string $email, string $password, string $type = 'household', array $business = []): int
    {
        $name = trim($name);
        if (!in_array($type, ['household', 'business'], true)) {
            throw new VendException('BAD_REQUEST', 'Choose a household or business account.');
        }
        $company = mb_substr(trim((string) ($business['company_name'] ?? '')), 0, 160);
        $reg = strtoupper(preg_replace('/\s+/', '', (string) ($business['company_reg'] ?? '')));
        $vat = strtoupper(preg_replace('/\s+/', '', (string) ($business['vat_no'] ?? '')));
        if ($type === 'business') {
            if ($company === '') {
                throw new VendException('BAD_REQUEST', 'Enter the registered company name.');
            }
            if (!preg_match('/^[A-Z0-9\/-]{4,40}$/', $reg)) {
                throw new VendException('BAD_REQUEST', 'Enter the company registration number (CIPA UIN).');
            }
            if ($vat !== '' && !preg_match('/^[A-Z0-9\/-]{4,40}$/', $vat)) {
                throw new VendException('BAD_REQUEST', 'That VAT number does not look right.');
            }
        }
        $email = strtolower(trim($email));
        if ($name === '' || !filter_var($email, FILTER_VALIDATE_EMAIL)) {
            throw new VendException('BAD_REQUEST', 'Enter your name and a valid email address.');
        }
        if (strlen($password) < 8) {
            throw new VendException('BAD_REQUEST', 'Password must be at least 8 characters.');
        }
        if ($this->acc->one('SELECT id FROM {users} WHERE email = ?', [$email])) {
            throw new VendException('EXISTS', 'An account with this email already exists.', 409);
        }
        $this->acc->run('INSERT INTO {users} (name, account_type, company_name, company_reg, vat_no, email, password_hash) VALUES (?,?,?,?,?,?,?)', [$name, $type, $type === 'business' ? $company : null, $type === 'business' ? $reg : null,
                $type === 'business' && $vat !== '' ? $vat : null, $email, password_hash($password, PASSWORD_DEFAULT)]);
        $id = $this->acc->lastId();
        $this->app->audit->record("portal:$id", 'customer', 'portal.signup', 'portal_users', (string) $id, null, $type);
        return $id;
    }

    public function login(string $email, string $password): int
    {
        $u = $this->acc->one('SELECT id, password_hash FROM {users} WHERE email = ?', [strtolower(trim($email))]);
        $ok = $u && password_verify($password, $u['password_hash']);
        $this->app->audit->record('portal:' . ($u['id'] ?? '?'), 'customer', $ok ? 'portal.login' : 'portal.login_failed', 'portal_users', isset($u['id']) ? (string) $u['id'] : null);
        if (!$ok) {
            usleep(300_000);
            throw new VendException('BAD_LOGIN', 'Email or password is incorrect.', 401);
        }
        return (int) $u['id'];
    }

    public function me(int $uid): array
    {
        $u = $this->acc->one('SELECT id, name, account_type, company_name, company_reg, vat_no, email, msisdn, created_at FROM {users} WHERE id = ?', [$uid]);
        if (!$u) {
            throw new VendException('UNAUTHORISED', 'Please sign in.', 401);
        }
        return $u;
    }

    /** Send a 6-digit code by SMS (through sms_outbox) to prove the customer owns the number. */
    public function requestPhoneCode(int $uid, string $msisdn): array
    {
        $m = VendService::normaliseMsisdn($msisdn);
        if (!$m) {
            throw new VendException('BAD_REQUEST', 'Enter a valid Botswana mobile number.');
        }
        $other = $this->acc->one('SELECT id FROM {users} WHERE msisdn = ? AND id <> ?', [$m, $uid]);
        if ($other) {
            throw new VendException('EXISTS', 'That number is already verified on another account.', 409);
        }
        $recent = $this->acc->one("SELECT COUNT(*) n FROM {codes} WHERE user_id = ? AND purpose = 'phone' AND expires_at > NOW(6) - INTERVAL 50 MINUTE", [$uid]);
        if ((int) $recent['n'] >= 5) {
            throw new VendException('RATE_LIMIT', 'Too many codes requested. Try again in an hour.', 429);
        }
        $code = sprintf('%06d', random_int(0, 999999));
        $this->acc->run("INSERT INTO {codes} (user_id, purpose, target, code_hash, expires_at) VALUES (?, 'phone', ?, ?, NOW(6) + INTERVAL 10 MINUTE)",
            [$uid, $m, hash('sha256', $code)]);
        $this->pdo()->prepare('INSERT INTO sms_outbox (msisdn, body) VALUES (?, ?)')
            ->execute([$m, "Your Maru Power code is $code. It expires in 10 minutes. Do not share it."]);
        return ['sent_to' => $m, 'demo_code' => getenv('MV_DEMO') === '1' ? $code : null];
    }

    /** Verify the code; then link every meter that has bought tokens sent to this number. */
    public function verifyPhone(int $uid, string $code): array
    {
        $c = $this->acc->one("SELECT * FROM {codes} WHERE user_id = ? AND purpose = 'phone' AND used_at IS NULL
            AND expires_at > NOW(6) ORDER BY id DESC LIMIT 1", [$uid]);
        if (!$c || $c['attempts'] >= 5) {
            throw new VendException('BAD_CODE', 'Code expired. Request a new one.');
        }
        if (!hash_equals($c['code_hash'], hash('sha256', trim($code)))) {
            $this->acc->run('UPDATE {codes} SET attempts = attempts + 1 WHERE id = ?', [$c['id']]);
            throw new VendException('BAD_CODE', 'Incorrect code.');
        }
        // The account (Maru Quick database) is updated first; linking meters (Maru Vend) is safe to repeat.
        if ($this->acc->run('UPDATE {codes} SET used_at = NOW(6) WHERE id = ? AND used_at IS NULL', [$c['id']]) !== 1) {
            throw new VendException('BAD_CODE', 'Code already used. Request a new one.');
        }
        $this->acc->run('UPDATE {users} SET msisdn = ? WHERE id = ?', [$c['target'], $uid]);
        return Db::tx($this->pdo(), function (PDO $pdo) use ($uid, $c) {
            $linked = [];
            $skipped = [];
            $st = $pdo->prepare("SELECT meter_number, MAX(id) sale_id, MAX(customer_name) customer_name FROM vend_sales
                WHERE msisdn = ? AND state = 'SUCCEEDED' GROUP BY meter_number");
            $st->execute([$c['target']]);
            foreach ($st->fetchAll() as $row) {
                $r = $this->link($uid, $row['meter_number'], 'phone', (string) $row['sale_id'], $row['customer_name']);
                if ($r === true) {
                    $linked[] = $row['meter_number'];
                } elseif ($r === 'taken') {
                    $skipped[] = $row['meter_number'];
                }
            }
            $this->app->audit->record("portal:$uid", 'customer', 'portal.phone_verified', 'portal_users', (string) $uid, null, $c['target']);
            return ['msisdn' => $c['target'], 'linked' => $linked, 'owned_by_someone_else' => $skipped];
        });
    }

    // ------------------------------------------------------------------ linking meters

    /**
     * Link a meter using a purchase slip: receipt number + the full 20-digit token printed on it.
     * The teller's till, USSD or web store sale is the proof that this customer holds the meter.
     */
    /**
     * Add a meter by its number: checked with the token source, which returns the name on the meter.
     * Step 1 (confirm=false) returns that name for the customer to check; step 2 (confirm=true) adds it.
     * A meter that already has an owner cannot be added this way: the owner shares it instead.
     * Limited to 10 checks an hour per account.
     */
    public function addByNumber(int $uid, string $meter, bool $confirm, string $label = '', string $siteType = 'home'): array
    {
        $meter = preg_replace('/\D/', '', $meter);
        if (!preg_match('/^\d{11}$|^\d{13}$/', $meter)) {
            throw new VendException('BAD_METER', 'Meter numbers are 11 or 13 digits.');
        }
        if ($this->one('SELECT 1 FROM portal_meters WHERE user_id = ? AND meter_number = ?', [$uid, $meter])) {
            throw new VendException('EXISTS', 'This meter is already on your account.', 409);
        }
        if ($this->one("SELECT 1 FROM portal_meters WHERE meter_number = ? AND role = 'owner'", [$meter])) {
            throw new VendException('METER_OWNED', 'This meter is already managed by another Maru Power account. Ask its owner to share it with you, or contact support if you have moved in.', 409);
        }
        $recent = $this->one("SELECT COUNT(*) n FROM audit_log WHERE actor = ? AND action = 'portal.meter_checked' AND created_at > NOW(6) - INTERVAL 1 HOUR", ["portal:$uid"]);
        if ((int) $recent['n'] >= 10) {
            throw new VendException('RATE_LIMIT', 'Too many meter checks. Try again in an hour.', 429);
        }
        $this->app->audit->record("portal:$uid", 'customer', 'portal.meter_checked', 'portal_meters', $meter);
        $r = $this->app->provider()->confirmCustomer('CHK' . bin2hex(random_bytes(8)), $meter, 1000, 'portal');
        if (!$r->ok()) {
            throw $r->outcome === \MaruVend\Provider\ProviderResult::BUSINESS_FAULT
                ? new VendException('METER_REJECTED', 'That meter could not be found. Check the number and try again.')
                : new VendException('UNAVAILABLE', 'Meters cannot be checked right now. Please try again shortly.', 503);
        }
        $name = (string) ($r->data['customerName'] ?? '');
        if (!$confirm) {
            return ['meter_number' => $meter, 'customer_name' => $name];
        }
        $res = Db::tx($this->pdo(), fn () => $this->link($uid, $meter, 'number', null, $name, $label, $siteType));
        if ($res === 'taken') {
            throw new VendException('METER_OWNED', 'This meter is already managed by another Maru Power account.', 409);
        }
        return $this->meter($uid, $meter);
    }

    public function claimByReceipt(int $uid, string $receiptNo, string $token, string $label = '', string $siteType = 'home'): array
    {
        $recent = $this->one("SELECT COUNT(*) n FROM audit_log WHERE actor = ? AND action = 'portal.claim_failed' AND created_at > NOW(6) - INTERVAL 1 HOUR", ["portal:$uid"]);
        if ((int) $recent['n'] >= self::MAX_CLAIM_ATTEMPTS) {
            throw new VendException('RATE_LIMIT', 'Too many attempts. Try again in an hour.', 429);
        }
        $token = preg_replace('/\D/', '', $token);
        $s = $this->one("SELECT s.id, s.meter_number, s.customer_name, t.token FROM vend_sales s JOIN vend_tokens t ON t.sale_id = s.id
            WHERE s.receipt_no = ? AND s.state = 'SUCCEEDED'", [strtoupper(trim($receiptNo))]);
        if (!$s || !hash_equals((string) $s['token'], $token)) {
            $this->app->audit->record("portal:$uid", 'customer', 'portal.claim_failed', 'vend_sales', null, null, substr(trim($receiptNo), 0, 32));
            throw new VendException('NO_MATCH', 'That receipt number and token do not match a completed purchase.');
        }
        $r = Db::tx($this->pdo(), fn () => $this->link($uid, $s['meter_number'], 'receipt', (string) $s['id'], $s['customer_name'], $label, $siteType));
        if ($r === 'taken') {
            throw new VendException('METER_OWNED', 'This meter is already managed by another Maru Power account. Ask its owner to share it with you, or contact support if you have moved in.', 409);
        }
        return $this->meter($uid, $s['meter_number']);
    }

    /** @return bool|string true = linked, false = already linked to this user, 'taken' = another owner */
    private function link(int $uid, string $meter, string $how, ?string $proof, ?string $customerName, string $label = '', string $siteType = 'home'): bool|string
    {
        if ($this->one('SELECT id FROM portal_meters WHERE user_id = ? AND meter_number = ?', [$uid, $meter])) {
            return false;
        }
        $owner = $this->one("SELECT user_id FROM portal_meters WHERE meter_number = ? AND role = 'owner' FOR UPDATE", [$meter]);
        if ($owner) {
            return 'taken';
        }
        $label = trim($label) !== '' ? mb_substr(trim($label), 0, 60) : ($customerName ? mb_substr($customerName, 0, 60) : 'Meter ' . substr($meter, -4));
        $this->pdo()->prepare("INSERT INTO portal_meters (user_id, meter_number, role, label, site_type, linked_by, proof) VALUES (?,?, 'owner', ?,?,?,?)")
            ->execute([$uid, $meter, $label, in_array($siteType, ['home', 'business', 'other'], true) ? $siteType : 'home', $how, $proof]);
        $this->app->audit->record("portal:$uid", 'customer', 'portal.meter_linked', 'portal_meters', $meter, null, "$how:$proof");
        return true;
    }

    private function access(int $uid, string $meter): array
    {
        $a = $this->one('SELECT * FROM portal_meters WHERE user_id = ? AND meter_number = ?', [$uid, $meter]);
        if (!$a) {
            throw new VendException('NOT_FOUND', 'Meter not found on your account.', 404);
        }
        return $a;
    }

    private function owner(int $uid, string $meter): array
    {
        $a = $this->access($uid, $meter);
        if ($a['role'] !== 'owner') {
            throw new VendException('FORBIDDEN', 'Only the meter owner can do that.', 403);
        }
        return $a;
    }

    public function updateMeter(int $uid, string $meter, array $b): array
    {
        $a = $this->access($uid, $meter);
        $label = isset($b['label']) ? mb_substr(trim((string) $b['label']), 0, 60) : $a['label'];
        $type = in_array($b['site_type'] ?? '', ['home', 'business', 'other'], true) ? $b['site_type'] : $a['site_type'];
        $this->pdo()->prepare('UPDATE portal_meters SET label = ?, site_type = ? WHERE id = ?')->execute([$label ?: $a['label'], $type, $a['id']]);
        return $this->meter($uid, $meter);
    }

    public function unlink(int $uid, string $meter): void
    {
        $a = $this->access($uid, $meter);
        if ($a['role'] === 'owner') {
            $this->pdo()->prepare('DELETE FROM portal_meters WHERE meter_number = ?')->execute([$meter]); // members lose access too
        } else {
            $this->pdo()->prepare('DELETE FROM portal_meters WHERE id = ?')->execute([$a['id']]);
        }
        $this->app->audit->record("portal:$uid", 'customer', 'portal.meter_unlinked', 'portal_meters', $meter);
    }

    public function share(int $uid, string $meter, string $email): array
    {
        $a = $this->owner($uid, $meter);
        $u = $this->acc->one('SELECT id FROM {users} WHERE email = ?', [strtolower(trim($email))]);
        if (!$u) {
            throw new VendException('NOT_FOUND', 'No Maru Power account uses that email. Ask them to sign up first.', 404);
        }
        if ((int) $u['id'] !== $uid) {
            $this->pdo()->prepare("INSERT IGNORE INTO portal_meters (user_id, meter_number, role, label, site_type, linked_by, proof) VALUES (?,?, 'member', ?,?, 'shared', ?)")
                ->execute([$u['id'], $meter, $a['label'], $a['site_type'], (string) $uid]);
            $this->app->audit->record("portal:$uid", 'customer', 'portal.meter_shared', 'portal_meters', $meter, null, (string) $u['id']);
        }
        return $this->meter($uid, $meter);
    }

    public function unshare(int $uid, string $meter, int $memberId): array
    {
        $this->owner($uid, $meter);
        $this->pdo()->prepare("DELETE FROM portal_meters WHERE meter_number = ? AND user_id = ? AND role = 'member'")->execute([$meter, $memberId]);
        return $this->meter($uid, $meter);
    }

    // ------------------------------------------------------------------ reading

    public function meters(int $uid): array
    {
        $rows = $this->all("SELECT pm.meter_number, pm.role, pm.label, pm.site_type, pm.linked_by, pm.created_at,
              (SELECT MAX(customer_name) FROM vend_sales s WHERE s.meter_number = pm.meter_number) customer_name,
              (SELECT COUNT(*) FROM vend_sales s WHERE s.meter_number = pm.meter_number AND s.state = 'SUCCEEDED') purchases,
              (SELECT COALESCE(SUM(s.amount_thebe),0) FROM vend_sales s WHERE s.meter_number = pm.meter_number AND s.state = 'SUCCEEDED'
                  AND s.resolved_at >= DATE_FORMAT(CURDATE(), '%Y-%m-01')) month_thebe,
              (SELECT COALESCE(SUM(t.kwh),0) FROM vend_sales s JOIN vend_tokens t ON t.sale_id = s.id WHERE s.meter_number = pm.meter_number
                  AND s.resolved_at >= DATE_FORMAT(CURDATE(), '%Y-%m-01')) month_kwh,
              (SELECT COUNT(*) FROM vend_sales s WHERE s.meter_number = pm.meter_number AND s.state IN ('RESERVED','SUBMITTED','UNKNOWN','MANUAL_REVIEW')) in_progress
            FROM portal_meters pm WHERE pm.user_id = ? ORDER BY pm.site_type, pm.label", [$uid]);
        foreach ($rows as &$r) {
            $r['last'] = $this->lastToken($r['meter_number']);
        }
        return $rows;
    }

    private function lastToken(string $meter): ?array
    {
        return $this->one("SELECT s.id, s.receipt_no, s.amount_thebe, t.token, t.kwh, t.issued_at FROM vend_sales s JOIN vend_tokens t ON t.sale_id = s.id
            WHERE s.meter_number = ? AND s.state = 'SUCCEEDED' ORDER BY s.id DESC LIMIT 1", [$meter]);
    }

    public function meter(int $uid, string $meter): array
    {
        $a = $this->access($uid, $meter);
        $m = array_values(array_filter($this->meters($uid), fn ($r) => $r['meter_number'] === $meter))[0];
        $m['transactions'] = $this->transactions($uid, $meter, 100);
        if ($a['role'] === 'owner') {
            // Access is in Maru Vend; names and emails come from the account database.
            $access = $this->all("SELECT user_id, role, linked_by FROM portal_meters WHERE meter_number = ? ORDER BY role = 'owner' DESC, id", [$meter]);
            $ids = array_map(fn ($r) => (int) $r['user_id'], $access);
            $people = $ids ? array_column($this->acc->all('SELECT id, name, email FROM {users} WHERE id IN (' . implode(',', array_fill(0, count($ids), '?')) . ')', $ids), null, 'id') : [];
            $m['members'] = array_values(array_filter(array_map(fn ($r) => isset($people[$r['user_id']])
                ? ['id' => (int) $r['user_id'], 'name' => $people[$r['user_id']]['name'], 'email' => $people[$r['user_id']]['email'], 'role' => $r['role'], 'linked_by' => $r['linked_by']]
                : null, $access)));
        }
        return $m;
    }

    /** Sales on the customer's meters from every channel, newest first. */
    public function transactions(int $uid, ?string $meter = null, int $limit = 50): array
    {
        $sql = "SELECT s.id, s.receipt_no, s.meter_number, s.amount_thebe, s.state, s.created_at, s.resolved_at, c.type channel,
                m.name outlet, t.kwh, t.token, pm.label
            FROM vend_sales s JOIN portal_meters pm ON pm.meter_number = s.meter_number AND pm.user_id = ?
            JOIN channels c ON c.id = s.channel_id JOIN merchants m ON m.id = s.merchant_id
            LEFT JOIN vend_tokens t ON t.sale_id = s.id
            WHERE s.state NOT IN ('QUOTED','EXPIRED')" . ($meter ? ' AND s.meter_number = ?' : '') . ' ORDER BY s.id DESC LIMIT ' . max(1, min(500, $limit));
        $rows = $this->all($sql, $meter ? [$uid, $meter] : [$uid]);
        foreach ($rows as &$r) {
            $r['verified'] = $r['state'] === SaleState::SUCCEEDED;
            $r['message'] = SaleState::customerMessage($r['state']);
        }
        return $rows;
    }

    /**
     * One transaction with its receipt and the evidence trail:
     *   1. payment received (cash at a till against the outlet's float, or a verified provider payment),
     *   2. amount set aside for the purchase (float reserve),
     *   3. token issued,
     *   4. purchase completed (or released / reversed if no token).
     * Wording is customer-facing: it does not name the utility or internal systems.
     */
    public function transaction(int $uid, int $saleId): array
    {
        $s = $this->app->vend()->sale($saleId);
        $this->access($uid, $s['meter_number']);
        $ch = $this->one('SELECT c.type, m.name, m.code FROM channels c JOIN merchants m ON m.id = c.merchant_id WHERE c.id = ?', [$s['channel_id']]);
        $pay = $this->all('SELECT provider, payment_ref, amount_thebe, status, reason, received_at FROM payments WHERE sale_id = ? ORDER BY id', [$saleId]);
        $ledger = $this->all('SELECT entry_type, amount_thebe, created_at FROM float_ledger WHERE sale_id = ? ORDER BY id', [$saleId]);
        $events = $this->all('SELECT at, to_state, cause FROM sale_events WHERE sale_id = ? ORDER BY seq', [$saleId]);
        $has = fn (string $type) => array_values(array_filter($ledger, fn ($l) => $l['entry_type'] === $type))[0] ?? null;

        $verified = array_values(array_filter($pay, fn ($p) => $p['status'] === 'verified'))[0] ?? null;
        $checks = [];
        if ($ch['type'] === 'POS') {
            $checks[] = ['name' => 'Payment received', 'ok' => (bool) $has('reserve'),
                'detail' => "Paid at {$ch['name']} (till). The outlet's prepaid float covered the sale."];
        } else {
            $checks[] = ['name' => 'Payment received', 'ok' => (bool) $verified,
                'detail' => $verified ? sprintf('%s confirmed payment ref %s for P%.2f, matching the sale amount.', self::providerName($verified['provider']), $verified['payment_ref'], $verified['amount_thebe'] / 100)
                    : ($pay ? 'Payment rejected: ' . $pay[0]['reason'] : 'Waiting for the payment provider to confirm.')];
        }
        $checks[] = ['name' => 'Amount set aside', 'ok' => (bool) $has('reserve'), 'detail' => $has('reserve') ? 'The amount was set aside for your purchase at ' . substr($has('reserve')['created_at'], 0, 19) : 'Not yet set aside.'];
        $checks[] = ['name' => 'Token issued', 'ok' => !empty($s['token']), 'detail' => $s['token'] ? 'Reference ' . ($s['provider_ref'] ?: '—') . ', issued ' . substr((string) $s['issued_at'], 0, 19) : $s['message']];
        $settled = $has('settle');
        $released = $has('release') ?? $has('refund');
        $checks[] = ['name' => 'Purchase completed', 'ok' => (bool) $settled,
            'detail' => $settled ? 'The purchase was completed and recorded.' : ($released ? 'No token was issued, so the amount was released and the payment reversed.' : 'Pending.')];

        return [
            'sale' => \MaruVend\Api\ApiApp::view($s, $this->app) + ['channel' => $ch['type'], 'outlet' => $ch['name'], 'created_at' => $s['created_at']],
            'verified' => !in_array(false, array_column($checks, 'ok'), true),
            'checks' => $checks,
            'timeline' => array_map(fn ($e) => ['at' => $e['at'], 'to_state' => $e['to_state'], 'cause' => self::customerStep($e['to_state'])], $events),
        ];
    }

    /** Customer wording for each step of a sale (internal records keep the technical cause). */
    public static function customerStep(string $state): string
    {
        return match ($state) {
            SaleState::QUOTED => 'Meter details confirmed',
            SaleState::PAYMENT_PENDING => 'Waiting for payment',
            SaleState::RESERVED => 'Payment confirmed; amount set aside',
            SaleState::SUBMITTED => 'Token requested',
            SaleState::SUCCEEDED => 'Token issued',
            SaleState::UNKNOWN, SaleState::MANUAL_REVIEW => 'Confirming the token, do not pay again',
            SaleState::FAILED => 'No token issued; payment reversed',
            SaleState::EXPIRED => 'Request expired',
            default => 'Updated',
        };
    }

    public static function providerName(string $p): string
    {
        return match (true) {
            str_starts_with($p, 'channel:'), $p === 'test' => 'Test payment',
            default => ucwords(str_replace('-', ' ', $p)),
        };
    }

    public function dashboard(int $uid): array
    {
        $meters = $this->meters($uid);
        $trend = $this->all("SELECT DATE_FORMAT(s.resolved_at, '%Y-%m') ym, COALESCE(SUM(t.kwh),0) kwh, SUM(s.amount_thebe) thebe
            FROM vend_sales s JOIN vend_tokens t ON t.sale_id = s.id JOIN portal_meters pm ON pm.meter_number = s.meter_number AND pm.user_id = ?
            WHERE s.state = 'SUCCEEDED' AND s.resolved_at >= DATE_FORMAT(CURDATE() - INTERVAL 5 MONTH, '%Y-%m-01') GROUP BY ym ORDER BY ym", [$uid]);
        $byYm = array_column($trend, null, 'ym');
        $months = [];
        for ($i = 5; $i >= 0; $i--) {
            $ym = date('Y-m', strtotime("first day of -$i month"));
            $months[] = ['ym' => $ym, 'label' => date('M', strtotime("$ym-01")), 'kwh' => (float) ($byYm[$ym]['kwh'] ?? 0), 'thebe' => (int) ($byYm[$ym]['thebe'] ?? 0)];
        }
        return [
            'user' => $this->me($uid),
            'meters' => $meters,
            'month_thebe' => array_sum(array_column($meters, 'month_thebe')),
            'month_kwh' => round(array_sum(array_column($meters, 'month_kwh')), 1),
            'in_progress' => array_sum(array_column($meters, 'in_progress')),
            'trend' => $months,
            'recent' => $this->transactions($uid, null, 8),
        ];
    }

    // ------------------------------------------------------------------ buying

    /** The channel Maru Power sells through (MV_PORTAL_KEY, default the app channel). */
    private function channel(): array
    {
        $c = $this->one('SELECT * FROM channels WHERE api_key = ? AND active = 1', [getenv('MV_PORTAL_KEY') ?: 'app-demo']);
        if (!$c) {
            throw new VendException('NOT_CONFIGURED', 'Buying in Maru Power is not set up yet.', 503);
        }
        return $c;
    }

    public function quote(int $uid, string $meter, float $amount, string $key): array
    {
        $this->access($uid, $meter);
        $u = $this->me($uid);
        $ch = $this->channel();
        $s = $this->app->vend()->quote($ch, $meter, (int) round($amount * 100), 'mp' . $uid . '-' . substr($key, 0, 40), $u['msisdn']);
        $this->pdo()->prepare('UPDATE vend_sales SET portal_user_id = ? WHERE id = ? AND portal_user_id IS NULL')->execute([$uid, $s['id']]);
        $s = $this->app->vend()->accept($ch, (int) $s['id']);
        return \MaruVend\Api\ApiApp::view($s, $this->app);
    }

    /**
     * Ask the provider to collect payment. In the test environment the payment is approved at once and
     * goes through the same verification (amount match, one-time reference) as a real provider callback.
     * In production the sale waits for the provider's signed callback.
     */
    public function pay(int $uid, int $saleId, string $method): array
    {
        $s = $this->app->vend()->sale($saleId);
        if ((int) ($s['portal_user_id'] ?? 0) !== $uid) {
            throw new VendException('NOT_FOUND', 'Sale not found', 404);
        }
        if (!isset(\MaruVend\Channels\PaymentGateway::METHODS[$method])) {
            throw new VendException('BAD_METHOD', 'Choose a payment method.', 422);
        }
        if (\MaruVend\Channels\PaymentGateway::testMode()) {
            $s = $this->app->vend()->verifyPayment($saleId, 'test', "TEST-$method-$saleId", (int) $s['amount_thebe'], "test:$method:$saleId");
        }
        return \MaruVend\Api\ApiApp::view($s, $this->app) + ['awaiting_provider' => !\MaruVend\Channels\PaymentGateway::testMode()];
    }

    public function status(int $uid, int $saleId): array
    {
        return $this->transaction($uid, $saleId);
    }
}
