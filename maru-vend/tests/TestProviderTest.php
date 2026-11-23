<?php
declare(strict_types=1);

namespace MaruVend\Tests;

use MaruVend\Provider\ProviderResult;
use MaruVend\Provider\TestProvider;

final class TestProviderTest extends \PHPUnit\Framework\TestCase
{
    public function testIssuesRepeatableTestTokensAndRejectsBlockedMeters(): void
    {
        $p = new TestProvider();
        $a = $p->creditVend('SALE1', '94949494949', 5000, 't');
        $this->assertSame(ProviderResult::OK, $a->outcome);
        $this->assertMatchesRegularExpression('/^\d{20}$/', $a->data['token']);
        $this->assertSame($a->data['token'], $p->creditVend('SALE1', '94949494949', 5000, 't')->data['token']);
        $this->assertNotSame($a->data['token'], $p->creditVend('SALE2', '94949494949', 5000, 't')->data['token']);
        $d = $a->data;
        $this->assertSame(5000, $d['costUnitsThebe'] + $d['fixedChargeThebe'] + $d['govLevyThebe'] + $d['vatThebe']);
        $this->assertSame(ProviderResult::BUSINESS_FAULT, $p->confirmCustomer('X', '00001234567', 5000, 't')->outcome);
    }
}
