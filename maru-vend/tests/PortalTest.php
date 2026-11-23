<?php
declare(strict_types=1);

namespace MaruVend\Tests;

use MaruVend\Portal\Portal;
use MaruVend\Vend\VendException;

final class PortalTest extends TestCase
{
    private Portal $portal;

    protected function setUp(): void
    {
        parent::setUp();
        putenv('MV_PAYMENTS=test');
        $this->pdo->exec("INSERT INTO channels (id, merchant_id, type, is_24h, api_key, api_secret) VALUES (3,1,'APP',1,'app-demo','app-secret')");
        $this->portal = new Portal($this->app);
    }

    /** A teller sells at the till; the slip then links the meter to the customer's account. */
    private function tillSale(string $meter = '94949494949', string $token = '12345678901234567890', ?string $msisdn = null): array
    {
        $this->provider->vendQueue[] = FakeProvider::token($token);
        $s = $this->vend->quote($this->pos, $meter, 2500, 'k' . bin2hex(random_bytes(6)), $msisdn);
        $this->vend->accept($this->pos, (int) $s['id']);
        $this->vend->processVend((int) $s['id']);
        return $this->vend->sale((int) $s['id']);
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

    public function testTillSaleLinksByReceiptAndShowsVerifiedInAccount(): void
    {
        $sale = $this->tillSale();
        $uid = $this->portal->signup('Lethabo M', 'l@example.com', 'secret123');
        $m = $this->portal->claimByReceipt($uid, $sale['receipt_no'], '1234 5678 9012 3456 7890', 'Home', 'home');
        $this->assertSame('owner', $m['role']);
        $this->assertCount(1, $m['transactions']);

        $tx = $this->portal->transaction($uid, (int) $sale['id']);
        $this->assertTrue($tx['verified']);
        $this->assertSame([true, true, true, true], array_column($tx['checks'], 'ok'));
        $this->assertSame('POS', $tx['sale']['channel']);

        // Later sales on the same meter from any channel show up without doing anything.
        $this->tillSale(token: '99998888777766665555');
        $this->assertCount(2, $this->portal->transactions($uid));
    }

    public function testWrongTokenDoesNotLinkAndIsRateLimited(): void
    {
        $sale = $this->tillSale();
        $uid = $this->portal->signup('A', 'a@example.com', 'secret123');
        for ($i = 0; $i < Portal::MAX_CLAIM_ATTEMPTS; $i++) {
            $this->expectCode('NO_MATCH', fn () => $this->portal->claimByReceipt($uid, $sale['receipt_no'], '00000000000000000000'));
        }
        $this->expectCode('RATE_LIMIT', fn () => $this->portal->claimByReceipt($uid, $sale['receipt_no'], '12345678901234567890'));
        $this->assertSame([], $this->portal->meters($uid));
    }

    public function testSecondAccountCannotTakeAnOwnedMeterButCanBeShared(): void
    {
        $sale = $this->tillSale();
        $owner = $this->portal->signup('Owner', 'o@example.com', 'secret123');
        $other = $this->portal->signup('Other', 'x@example.com', 'secret123');
        $this->portal->claimByReceipt($owner, $sale['receipt_no'], '12345678901234567890');
        $this->expectCode('METER_OWNED', fn () => $this->portal->claimByReceipt($other, $sale['receipt_no'], '12345678901234567890'));
        $this->expectCode('NOT_FOUND', fn () => $this->portal->transaction($other, (int) $sale['id']));

        $this->portal->share($owner, '94949494949', 'x@example.com');
        $this->assertSame('member', $this->portal->meters($other)[0]['role']);
        $this->expectCode('FORBIDDEN', fn () => $this->portal->share($other, '94949494949', 'o@example.com'));
        $this->portal->unlink($owner, '94949494949');
        $this->assertSame([], $this->portal->meters($other));
    }

    public function testVerifiedPhoneLinksMetersWhoseTokensWereSentToIt(): void
    {
        putenv('MV_DEMO=1');
        $this->tillSale('94949494949', msisdn: '71234567');
        $this->tillSale('1234567890123', '11112222333344445555', '71234567');
        $this->tillSale('55555555555', '66667777888899990000', '72000000');
        $uid = $this->portal->signup('B', 'b@example.com', 'secret123');
        $code = $this->portal->requestPhoneCode($uid, '71 234 567')['demo_code'];
        $this->expectCode('BAD_CODE', fn () => $this->portal->verifyPhone($uid, '000000' === $code ? '111111' : '000000'));
        $r = $this->portal->verifyPhone($uid, $code);
        sort($r['linked'], SORT_STRING);
        $this->assertSame(['1234567890123', '94949494949'], $r['linked']);
        putenv('MV_DEMO');
    }

    public function testBuyingInPortalGoesThroughPaymentVerification(): void
    {
        $sale = $this->tillSale();
        $uid = $this->portal->signup('C', 'c@example.com', 'secret123');
        $this->portal->claimByReceipt($uid, $sale['receipt_no'], '12345678901234567890');

        $q = $this->portal->quote($uid, '94949494949', 50, 'key1');
        $this->assertSame('PAYMENT_PENDING', $q['status']);
        $paid = $this->portal->pay($uid, $q['sale_id'], 'orange-money');
        $this->assertSame('RESERVED', $paid['status']);
        $this->provider->vendQueue[] = FakeProvider::token('22223333444455556666');
        $this->vend->processVend($q['sale_id']);
        $tx = $this->portal->transaction($uid, $q['sale_id']);
        $this->assertTrue($tx['verified']);
        $this->assertStringContainsString('matching the sale amount', $tx['checks'][0]['detail']);

        // Cannot buy for a meter that is not on the account.
        $this->expectCode('NOT_FOUND', fn () => $this->portal->quote($uid, '55555555555', 50, 'key2'));
    }

    public function testPaymentMustMatchAmountAndReferenceIsSingleUse(): void
    {
        $a = $this->vend->accept($this->web, (int) $this->vend->quote($this->web, '94949494949', 5000, 'w1')['id']);
        $b = $this->vend->accept($this->web, (int) $this->vend->quote($this->web, '94949494949', 5000, 'w2')['id']);

        $this->expectCode('PAYMENT_REJECTED', fn () => $this->vend->verifyPayment((int) $a['id'], 'fnb', 'REF1', 4999, '{}'));
        $this->assertSame('PAYMENT_PENDING', $this->vend->sale((int) $a['id'])['state']);
        $this->assertSame('rejected', $this->pdo->query("SELECT status FROM payments WHERE payment_ref='REF1'")->fetchColumn());

        $this->vend->verifyPayment((int) $a['id'], 'fnb', 'REF2', 5000, '{}');
        $this->assertSame('RESERVED', $this->vend->sale((int) $a['id'])['state']);
        $this->vend->verifyPayment((int) $a['id'], 'fnb', 'REF2', 5000, '{}'); // provider retry: no-op
        $this->expectCode('PAYMENT_REUSED', fn () => $this->vend->verifyPayment((int) $b['id'], 'fnb', 'REF2', 5000, '{}'));
        $this->assertSame('PAYMENT_PENDING', $this->vend->sale((int) $b['id'])['state']);
    }

    public function testSignedProviderCallback(): void
    {
        putenv('MV_PAY_SECRET_FNB=shh');
        $ts = (string) time();
        $body = '{"sale_id":1,"payment_ref":"X","amount_thebe":100}';
        $sig = \MaruVend\Api\PaymentCallback::sign('shh', $ts, $body);
        $this->assertTrue(\MaruVend\Api\PaymentCallback::verify('fnb', $ts, $sig, $body));
        $this->assertFalse(\MaruVend\Api\PaymentCallback::verify('fnb', $ts, $sig, str_replace('100', '1000', $body)));
        $this->assertFalse(\MaruVend\Api\PaymentCallback::verify('orange-money', $ts, $sig, $body)); // no secret configured
        putenv('MV_PAY_SECRET_FNB');
    }
}
