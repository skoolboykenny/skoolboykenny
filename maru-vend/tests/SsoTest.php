<?php
declare(strict_types=1);

namespace MaruVend\Tests;

use MaruVend\Portal\Sso;

final class SsoTest extends TestCase
{
    private const SECRET = 'test-secret-that-is-at-least-32-chars';

    public function testTicketWorksOnceAndOnlyWhenSignedAndFresh(): void
    {
        $t = Sso::make(self::SECRET, 42);
        $this->assertSame(42, Sso::redeem($this->pdo, self::SECRET, $t));
        $this->assertNull(Sso::redeem($this->pdo, self::SECRET, $t), 'second use refused');

        $this->assertNull(Sso::redeem($this->pdo, 'another-secret-also-32-characters-long', Sso::make(self::SECRET, 42)), 'wrong secret');
        [$body, $sig] = explode('.', Sso::make(self::SECRET, 42));
        $forged = rtrim(strtr(base64_encode(str_replace('42', '43', base64_decode(strtr($body, '-_', '+/')))), '+/', '-_'), '=');
        $this->assertNull(Sso::redeem($this->pdo, self::SECRET, "$forged.$sig"), 'changed account id');
        $this->assertNull(Sso::redeem($this->pdo, self::SECRET, Sso::make(self::SECRET, 42, time() - 120)), 'expired');
        $this->assertNull(Sso::redeem($this->pdo, self::SECRET, 'garbage'));
    }
}
