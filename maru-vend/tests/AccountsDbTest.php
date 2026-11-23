<?php
declare(strict_types=1);

namespace MaruVend\Tests;

use MaruVend\Portal\Accounts;
use MaruVend\Portal\Portal;

/** Maru Power accounts kept in a separate (Maru Quick) database; meters and sales stay in Maru Vend. */
final class AccountsDbTest extends TestCase
{
    private Accounts $acc;
    private Portal $portal;

    protected function setUp(): void
    {
        parent::setUp();
        $pdo = Accounts::connect(['host' => '127.0.0.1', 'port' => 3306, 'name' => getenv('MQ_TEST_DB') ?: 'maruquick_test',
            'user' => 'maruvend', 'pass' => getenv('MV_DB_PASS') ?: 'devpass']);
        $pdo->exec('DROP TABLE IF EXISTS power_codes');
        $pdo->exec('DROP TABLE IF EXISTS power_users');
        $sql = (string) file_get_contents(__DIR__ . '/../../website/sql/maru_power_accounts.sql');
        foreach (array_filter(array_map('trim', preg_split('/;\s*$/m', $sql))) as $stmt) {
            if (preg_match('/^CREATE TABLE/m', $stmt)) {
                $pdo->exec($stmt);
            }
        }
        $this->acc = new Accounts($pdo, 'power_users', 'power_codes');
        $this->portal = new Portal($this->app, $this->acc);
    }

    public function testAccountsLiveInMaruQuickDatabaseAndSalesInMaruVend(): void
    {
        putenv('MV_DEMO=1');
        $this->provider->vendQueue[] = FakeProvider::token('12345678901234567890');
        $s = $this->vend->quote($this->pos, '94949494949', 2500, 'k1', '71234567');
        $this->vend->accept($this->pos, (int) $s['id']);
        $this->vend->processVend((int) $s['id']);
        $sale = $this->vend->sale((int) $s['id']);

        $biz = $this->portal->signup('Boi M', 'boi@example.com', 'secret123', 'business', ['company_name' => 'Kgosi Traders', 'company_reg' => 'BW00001234567']);
        $home = $this->portal->signup('Neo K', 'neo@example.com', 'secret123');

        // Accounts are in the Maru Quick database, none in Maru Vend.
        $this->assertSame('business', $this->acc->one('SELECT account_type FROM {users} WHERE email = ?', ['boi@example.com'])['account_type']);
        $this->assertSame(0, (int) $this->pdo->query('SELECT COUNT(*) FROM portal_users')->fetchColumn());
        $this->assertSame($biz, $this->portal->login('boi@example.com', 'secret123'));

        // Meters and sales (Maru Vend) attach to those accounts.
        $this->portal->claimByReceipt($biz, $sale['receipt_no'], '12345678901234567890', 'Shop', 'business');
        $this->portal->share($biz, '94949494949', 'neo@example.com');
        $this->assertSame(['Boi M', 'Neo K'], array_column($this->portal->meter($biz, '94949494949')['members'], 'name'));
        $this->assertCount(1, $this->portal->transactions($home));

        $code = $this->portal->requestPhoneCode($home, '71234567')['demo_code'];
        $this->portal->verifyPhone($home, $code);
        $this->assertSame('71234567', $this->acc->one('SELECT msisdn FROM {users} WHERE id = ?', [$home])['msisdn']);
        putenv('MV_DEMO');
    }
}
