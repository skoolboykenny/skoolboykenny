<?php
declare(strict_types=1);

namespace MaruVend\Tests;

use MaruVend\Api\HmacAuth;

final class AuditAndControlsTest extends TestCase
{
    public function testAuditChainVerifiesAndDetectsDirectEdits(): void
    {
        $s = $this->posSale();
        $this->vend->processVend((int) $s['id']);
        $this->assertTrue($this->app->audit->verify()['ok']);

        // Tamper: an administrator edits a row directly in the database.
        $this->pdo->exec("UPDATE audit_log SET new_value = 'FAILED' WHERE action = 'sale.succeeded'");
        $r = $this->app->audit->verify();
        $this->assertFalse($r['ok']);
        $this->assertStringContainsString('content does not match', implode(' ', $r['problems']));
    }

    public function testAuditDetectsDeletedRow(): void
    {
        $s = $this->posSale();
        $this->vend->processVend((int) $s['id']);
        $id = (int) $this->pdo->query('SELECT MIN(id) + 1 FROM audit_log')->fetchColumn();
        $this->pdo->exec("DELETE FROM audit_log WHERE id = $id");
        $this->assertFalse($this->app->audit->verify()['ok']);
    }

    public function testAnchorDetectsDeletionOfNewestRows(): void
    {
        $s = $this->posSale();
        $this->vend->processVend((int) $s['id']);
        $this->app->audit->anchor();
        // Deleting the newest rows leaves an internally valid chain; only the signed anchor catches it.
        $this->pdo->exec('DELETE FROM audit_log ORDER BY id DESC LIMIT 1');
        $r = $this->app->audit->verify();
        $this->assertFalse($r['ok']);
        $this->assertStringContainsString('chain rewritten', implode(' ', $r['problems']));
    }

    public function testAnchorDetectsAFullyRecomputedChain(): void
    {
        $this->posSale();
        $this->app->audit->anchor();
        // An attacker with DB access rewrites a row AND recomputes every hash after it.
        $this->pdo->exec("UPDATE audit_log SET actor = 'someone-else' WHERE id = 1");
        $prev = \MaruVend\Audit\AuditLog::GENESIS;
        foreach ($this->pdo->query('SELECT * FROM audit_log ORDER BY id')->fetchAll() as $r) {
            $at = str_pad((string) $r['created_at'], 26, '0');
            $h = \MaruVend\Audit\AuditLog::hashRow(['actor' => $r['actor'], 'role' => $r['role'], 'action' => $r['action'],
                'entity' => $r['entity'], 'entity_id' => $r['entity_id'], 'old' => $r['old_value'], 'new' => $r['new_value'],
                'ip' => $r['ip'], 'at' => $at], $prev);
            $this->pdo->prepare('UPDATE audit_log SET prev_hash = ?, hash = ? WHERE id = ?')->execute([$prev, $h, $r['id']]);
            $prev = $h;
        }
        $r = $this->app->audit->verify();
        $this->assertFalse($r['ok']);
        $this->assertStringContainsString('chain rewritten', implode(' ', $r['problems']));
    }

    public function testTimeoutsDeriveFromBpcSettingWithoutRestart(): void
    {
        $s = $this->app->settings;
        $this->assertSame(130, $s->workerTimeout());
        $this->assertSame(150, $s->channelTimeout());
        $s->apply('bpc_timeout_s', '180', 'test', $this->app->audit);
        $this->assertSame(190, $s->workerTimeout());
        $this->assertSame(210, $s->channelTimeout());
    }

    public function testSensitiveSettingNeedsSecondAdministrator(): void
    {
        $ap = $this->app->approvals();
        $id = $ap->requestSetting('bpc_endpoint', 'https://vend.bpc.example:8443', 'alice');
        try {
            $ap->approve($id, 'alice');
            $this->fail('maker must not approve own change');
        } catch (\RuntimeException $e) {
            $this->assertStringContainsString('different administrator', $e->getMessage());
        }
        $this->assertSame('http://127.0.0.1:8099', $this->app->settings->endpoint());
        $ap->approve($id, 'bob');
        $this->assertSame('https://vend.bpc.example:8443', $this->app->settings->endpoint());
        $this->assertTrue($this->app->audit->verify()['ok']);
    }

    public function testEndpointSwitchesToBackupByIpOrFqdn(): void
    {
        $st = $this->app->settings;
        $st->apply('bpc_endpoint_backup', 'https://10.20.30.40:8443', 't', $this->app->audit);
        $st->apply('endpoint_active', 'backup', 't', $this->app->audit);
        $this->assertSame('https://10.20.30.40:8443', $st->endpoint());
    }

    public function testHmacAuthentication(): void
    {
        $auth = new HmacAuth($this->pdo);
        $ts = (string) time();
        $body = '{"meter":"94949494949"}';
        $sig = HmacAuth::sign('pos-secret', $ts, 'POST', '/v1/confirm', $body);
        $this->assertNotNull($auth->verify('pos', $ts, $sig, 'POST', '/v1/confirm', $body));
        $this->assertNull($auth->verify('pos', $ts, $sig, 'POST', '/v1/confirm', '{"meter":"1"}'), 'tampered body');
        $this->assertNull($auth->verify('pos', (string) (time() - 1000), $sig, 'POST', '/v1/confirm', $body), 'stale timestamp');
    }

    public function testReportsContainAnnexureFieldsAndPointInTime(): void
    {
        $s = $this->posSale(2500);
        $before = $this->pdo->query('SELECT NOW(6)')->fetchColumn();
        usleep(10000);
        $this->vend->processVend((int) $s['id']);

        $sales = $this->app->reports()->sales(date('Y-m-d'), date('Y-m-d', strtotime('+1 day')));
        $this->assertCount(1, $sales);
        foreach (['Receipt/Transaction number', 'Date and time of transaction', 'Meter number', 'Transaction amount tendered',
                     'kWh/Units issued', 'Token number', 'VAT', 'Customer name', 'Government levy', 'Fixed charge', 'Cost of units',
                     'Unit cost', 'Total amount', 'Tariff index', 'BPC VAT number'] as $col) {
            $this->assertArrayHasKey($col, $sales[0]);
        }

        $pit = $this->app->reports()->pointInTime($before);
        $this->assertSame('RESERVED', $pit[0]['Status at that time']);
        $now = $this->app->reports()->pointInTime(date('Y-m-d H:i:s', time() + 5));
        $this->assertSame('SUCCEEDED', $now[0]['Status at that time']);

        $inv = $this->app->reports()->serviceFeeInvoice(date('Y-m-d'), date('Y-m-d', strtotime('+1 day')));
        $this->assertSame('1.25', $inv['Service fee due']);
        $rec = $this->app->reports()->reconciliation(date('Y-m-d'), date('Y-m-d', strtotime('+1 day')));
        $this->assertSame('25.00', $rec['Sales (tokens issued)']);
        $this->assertSame('10000.00', $rec['Cash deposited with BPC']);
    }

    public function testWorkersStandByWhenThisSiteIsNotActive(): void
    {
        $guard = new \MaruVend\Queue\SiteGuard($this->pdo, $this->app->settings);
        putenv('MV_SITE=primary');
        $this->assertNull($guard->blockedReason());
        $this->app->settings->apply('active_site', 'dr', 'failover', $this->app->audit);
        $this->assertStringContainsString("active site is 'dr'", (string) $guard->blockedReason());

        $s = $this->posSale();
        $worker = new \MaruVend\Queue\Worker($this->pdo, $this->app->settings, $this->vend, 'test');
        $this->assertFalse($worker->runOnce(), 'worker must not take jobs at an inactive site');
        $this->assertSame('RESERVED', $this->vend->sale((int) $s['id'])['state']);
        $this->assertSame(0, $this->provider->vendCalls());
        putenv('MV_SITE');
    }
}
