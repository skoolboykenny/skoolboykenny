<?php
declare(strict_types=1);

namespace MaruVend\Tests;

use MaruVend\Portal\Portal;
use MaruVend\Teller\Teller;
use MaruVend\Vend\VendException;

final class TellerTest extends TestCase
{
    private Teller $t;
    private int $mgr;
    private int $cashier;

    protected function setUp(): void
    {
        parent::setUp();
        $this->pdo->exec("INSERT INTO tellers (id, merchant_id, username, name, role, pin_hash) VALUES
            (1, 1, 'boss', 'Boss Lady', 'manager', '" . password_hash('482916', PASSWORD_DEFAULT) . "'),
            (2, 1, 'neo', 'Neo Till', 'teller', '" . password_hash('730514', PASSWORD_DEFAULT) . "')");
        $this->t = new Teller($this->app);
        $this->mgr = 1;
        $this->cashier = 2;
    }

    private function expectCode(string $code, callable $fn): void
    {
        try {
            $fn();
            $this->fail("Expected $code");
        } catch (VendException $e) {
            $this->assertSame($code, $e->errorCode);
        }
    }

    public function testCashSaleIsCoveredByFloatAndIssuesTokenAtOnce(): void
    {
        $before = $this->float()['available'];
        $q = $this->t->quote($this->cashier, '9494 9494 949', 50, 'k1', '71234567');
        $this->assertSame(['QUOTED', 'Test Customer'], [$q['status'], $q['customer_name']]);
        $s = $this->t->sell($this->cashier, $q['sale_id']);
        $this->assertSame('SUCCEEDED', $s['status']);
        $this->assertNotEmpty($s['receipt']['token']);
        $this->assertSame($before - 5000, $this->float()['available']);
        $this->assertSame(2, (int) $this->pdo->query('SELECT teller_id FROM vend_sales WHERE id = ' . $q['sale_id'])->fetchColumn());
        $this->assertSame('POS', $this->pdo->query('SELECT c.type FROM vend_sales s JOIN channels c ON c.id = s.channel_id WHERE s.id = ' . $q['sale_id'])->fetchColumn());

        $day = $this->t->day($this->cashier);
        $this->assertSame([1, 5000], [$day['count'], $day['cash_thebe']]);
        $this->assertNull($day['float_available_thebe'], 'tellers do not see the float');
        $this->assertSame($s['receipt_no'], $this->t->reprint($this->cashier, $s['receipt_no'])['receipt_no']);
        $this->assertSame($s['receipt_no'], $this->t->reprint($this->cashier, '94949494949')['receipt_no']);
    }

    public function testAnotherTellersSaleCannotBeSoldAndManagerOnlyActions(): void
    {
        $q = $this->t->quote($this->mgr, '94949494949', 20, 'k2', null);
        $this->expectCode('NOT_FOUND', fn () => $this->t->sell($this->cashier, $q['sale_id']));
        $this->expectCode('FORBIDDEN', fn () => $this->t->day($this->cashier, true));
        $this->expectCode('FORBIDDEN', fn () => $this->t->addTeller($this->cashier, 'x', 'X', '583920', 'teller'));
        $this->expectCode('BAD_REQUEST', fn () => $this->t->addTeller($this->mgr, 'kago', 'Kago', '1234', 'teller'));
        $list = $this->t->addTeller($this->mgr, 'Kago', 'Kago M', '583920', 'teller');
        $this->assertContains('kago', array_column($list, 'username'));
        $this->assertSame(3, $this->t->login('kago', '583920'));
        $this->expectCode('BAD_REQUEST', fn () => $this->t->updateTeller($this->mgr, $this->mgr, ['active' => false]));
        $this->t->updateTeller($this->mgr, 3, ['active' => false]);
        $this->expectCode('BAD_LOGIN', fn () => $this->t->login('kago', '583920'));
    }

    public function testWrongPinLocksAfterFiveTries(): void
    {
        for ($i = 0; $i < Teller::MAX_FAILED_LOGINS; $i++) {
            $this->expectCode('BAD_LOGIN', fn () => $this->t->login('neo', '000000'));
        }
        $this->expectCode('LOCKED', fn () => $this->t->login('neo', '730514'));
        $this->t->updateTeller($this->mgr, 2, ['pin' => '615283']); // manager reset unlocks
        $this->assertSame(2, $this->t->login('neo', '615283'));
    }

    public function testSaleCanBeAddedToCustomersMaruPowerAccount(): void
    {
        $portal = new Portal($this->app);
        $uid = $portal->signup('Mpho D', 'mpho@example.com', 'secret123');
        $q = $this->t->quote($this->cashier, '94949494949', 30, 'k3', null);
        $this->expectCode('BAD_REQUEST', fn () => $this->t->linkCustomer($this->cashier, $q['sale_id'], 'mpho@example.com'));
        $this->t->sell($this->cashier, $q['sale_id']);
        $this->expectCode('NOT_FOUND', fn () => $this->t->linkCustomer($this->cashier, $q['sale_id'], 'nobody@example.com'));
        $this->assertSame('linked', $this->t->linkCustomer($this->cashier, $q['sale_id'], 'MPHO@example.com')['result']);
        $this->assertSame('94949494949', $portal->meters($uid)[0]['meter_number']);
        $this->assertCount(1, $portal->transactions($uid));
        $this->assertSame('already', $this->t->linkCustomer($this->cashier, $q['sale_id'], 'mpho@example.com')['result']);
    }
}
