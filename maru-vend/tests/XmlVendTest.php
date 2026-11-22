<?php
declare(strict_types=1);

namespace MaruVend\Tests;

use MaruVend\Provider\ProviderResult;
use MaruVend\Provider\XmlVend\FaultMap;
use MaruVend\Provider\XmlVend\XmlVendConfig;
use MaruVend\Provider\XmlVend\XmlVendMessages;
use MaruVend\Provider\XmlVend\XmlVendProvider;

/**
 * XMLVend 2.1 adapter. Schema tests validate the base-schema parts of our messages against the
 * published XMLVend base schema (tests/fixtures/xmlvend-base-2.0.xsd, Apache License 2.0).
 * Integration tests run against the BPC simulator's SOAP endpoint (skipped if it is not running).
 */
final class XmlVendTest extends TestCase
{
    private const SIM = 'http://127.0.0.1:8099';

    // ------------------------------------------------------------------ schema

    public function testLastResponseAdviceValidatesAgainstPublishedBaseSchema(): void
    {
        $c = new XmlVendConfig('6001234567890', 'maruvend', 'secret', '2.0');
        $xml = XmlVendMessages::lastRespAdviceReq($c, 'MV-W1', ['dateTime' => '20261122103000', 'uniqueNumber' => 42],
            ['dateTime' => '20261122102959', 'uniqueNumber' => 41]);
        $this->assertSchemaValid($xml, 'adviceReq');
    }

    public function testFaultResponseShapeValidatesAgainstPublishedBaseSchema(): void
    {
        // The simulator builds faults exactly as a server would (5.2.4.4); check our parser's input is schema-valid.
        $h = ['baseNs' => 'http://www.nrs.eskom.co.za/xmlvend/base/2.0/schema', 'client' => '6001234567890', 'terminal' => 'MV-W1', 'dt' => '20261122103000', 'un' => 7];
        require_once dirname(__DIR__) . '/simulator/xmlvend-helpers.php';
        $xml = \xv_fault('BlockedMeterEx', 'Meter is blocked', $h, 'This meter is blocked.');
        $this->assertSchemaValid($xml, 'xmlvendFaultResp');
        $f = XmlVendMessages::fault($this->dom($xml));
        $this->assertSame('BlockedMeterEx', $f['type']);
        $this->assertSame('This meter is blocked.', $f['customerMsg']);
    }

    public function testRequestsCarryMsgIdTerminalAndNoPlainPasswordInStoredCopy(): void
    {
        $c = new XmlVendConfig('6001234567890', 'maruvend', 's3cret');
        $xml = XmlVendMessages::creditVendReq($c, 'MV-W1', ['dateTime' => '20261122103000', 'uniqueNumber' => 5], '04040404040', 12550);
        $x = new \DOMXPath($this->dom($xml));
        $this->assertSame('creditVendReq', $x->query('//*[local-name()="Body"]/*')->item(0)->localName);
        $this->assertSame('http://www.nrs.eskom.co.za/xmlvend/revenue/2.1/schema', $x->query('//*[local-name()="Body"]/*')->item(0)->namespaceURI);
        $this->assertSame('20261122103000', $x->query('//*[local-name()="msgID"]/@dateTime')->item(0)->value);
        $this->assertSame('04040404040', $x->query('//*[local-name()="meterIdentifier"]/@msno')->item(0)->value);
        $this->assertSame('125.50', $x->query('//*[local-name()="amt"]/@value')->item(0)->value);
        $this->assertStringNotContainsString('s3cret', XmlVendMessages::redact($xml));
    }

    public function testFaultMapCoversSpecificationFaultTypes(): void
    {
        $this->assertSame(ProviderResult::BUSINESS_FAULT, FaultMap::outcome('b:BlockedMeterEx', 'creditvend'));
        $this->assertSame(ProviderResult::BUSINESS_FAULT, FaultMap::outcome('VendorCreditEx', 'creditvend'));
        $this->assertSame(ProviderResult::BUSINESS_FAULT, FaultMap::outcome('BpcTariffBlockedEx', 'creditvend'), 'utility extension');
        $this->assertSame(ProviderResult::SYSTEM_FAULT, FaultMap::outcome('SystemEx', 'creditvend'));
        $this->assertSame(ProviderResult::NOT_FOUND, FaultMap::outcome('LastResponseEx', 'advice'));
        $this->assertSame(ProviderResult::UNKNOWN, FaultMap::outcome('XMLVendSchemaEx', 'creditvend'), 'never assume failure on a credit vend');
        $this->assertSame(ProviderResult::UNKNOWN, FaultMap::outcome('SomethingNew', 'creditvend'));
    }

    // ------------------------------------------------------------------ against the simulator

    public function testSaleThroughSimulator(): void
    {
        $p = $this->provider('MV-T1');
        $c = $p->confirmCustomer('S1Q', '94949494949', 5000, 'POS');
        $this->assertTrue($c->ok(), (string) $c->message);
        $this->assertSame('Mpho Domestic', $c->data['customerName']);

        $r = $p->creditVend('S1', '94949494949', 5000, 'POS');
        $this->assertTrue($r->ok(), (string) $r->message);
        $this->assertMatchesRegularExpression('/^\d{20}$/', $r->data['token']);
        $this->assertSame(5000, $r->data['totalThebe'], 'cost + fixed + levy + VAT = amount paid');
        $this->assertGreaterThan(0, $r->data['fixedChargeThebe']);
        $this->assertGreaterThan(0, $r->data['govLevyThebe']);
        $this->assertGreaterThan(0, $r->data['vatThebe']);
        $this->assertSame('01', $r->data['tariffIndex']);
    }

    public function testBlockedMeterIsABusinessFault(): void
    {
        $this->simMode('reject');
        $r = $this->provider('MV-T2')->creditVend('S2', '94949494949', 2000, 'POS');
        $this->assertSame(ProviderResult::BUSINESS_FAULT, $r->outcome);
        $this->assertSame('BlockedMeterEx', $r->faultCode);
    }

    public function testSystemExIsRetryable(): void
    {
        $this->simMode('processing');
        $r = $this->provider('MV-T3')->creditVend('S3', '94949494949', 2000, 'POS');
        $this->assertSame(ProviderResult::SYSTEM_FAULT, $r->outcome);
        // Retry uses a new msgID (the server rejects duplicates) and succeeds.
        $r2 = $this->provider('MV-T3')->creditVend('S3', '94949494949', 2000, 'POS');
        $this->assertTrue($r2->ok(), (string) $r2->message);
        $this->assertSame(2, (int) $this->pdo->query("SELECT COUNT(DISTINCT msg_unique) FROM xmlvend_messages WHERE client_sale_id='S3' AND operation='creditvend'")->fetchColumn());
    }

    public function testLostResponseIsRecoveredByLastResponseOnTheSameTerminal(): void
    {
        $this->simMode('lost');
        $r = $this->provider('MV-T4')->creditVend('S4', '94949494949', 2000, 'POS');
        $this->assertTrue($r->ok(), 'token recovered by advice: ' . $r->message);
        $this->assertMatchesRegularExpression('/^\d{20}$/', $r->data['token']);
    }

    public function testLostWithoutTokenIsConfirmedNotProcessed(): void
    {
        $this->simMode('lostfail');
        $r = $this->provider('MV-T5')->creditVend('S5', '94949494949', 2000, 'POS');
        $this->assertSame(ProviderResult::NOT_FOUND, $r->outcome, 'LastResponseEx: not processed');
    }

    public function testAmbiguousTerminalIsNeverTreatedAsFailed(): void
    {
        // Sale S6's outcome is uncertain, then the same terminal sends another sale before advising.
        $this->simMode('lostfail');
        $this->app->settings->apply('advice_first_delay_s', '100', 't', $this->app->audit); // no inline advice: stays UNKNOWN
        $p = $this->provider('MV-T6');
        $this->assertSame(ProviderResult::UNKNOWN, $p->creditVend('S6', '94949494949', 2000, 'POS')->outcome);
        $this->assertTrue($p->creditVend('S7', '94949494949', 2000, 'POS')->ok());
        $a = $p->lastResponse('S6');
        $this->assertSame(ProviderResult::PENDING, $a->outcome, 'must not conclude "not processed"');
        $this->assertSame('LastResponseEx-AMBIGUOUS', $a->faultCode);
    }

    public function testKeyChangeTokensAreReturned(): void
    {
        $this->simMode('kct');
        $r = $this->provider('MV-T8')->creditVend('S8', '94949494949', 2000, 'POS');
        $this->assertTrue($r->ok());
        $this->assertMatchesRegularExpression('/^\d{20}$/', (string) $r->data['keyChange1']);
        $this->assertMatchesRegularExpression('/^\d{20}$/', (string) $r->data['keyChange2']);
    }

    public function testUnknownMeterOnConfirm(): void
    {
        $r = $this->provider('MV-T9')->confirmCustomer('S9Q', '11111111111', 2000, 'POS');
        $this->assertSame(ProviderResult::BUSINESS_FAULT, $r->outcome);
        $this->assertSame('UnknownMeterEx', $r->faultCode);
    }

    public function testFullSaleThroughVendServiceAndQueue(): void
    {
        $this->app->settings->apply('provider', 'xmlvend', 't', $this->app->audit);
        $p = $this->provider('MV-T10');
        $vend = new \MaruVend\Vend\VendService($this->pdo, $this->app->settings, $p, $this->app->audit);
        $s = $vend->quote($this->pos, '04040404040', 3000, 'xv-full');
        $vend->accept($this->pos, (int) $s['id']);
        $this->simMode('lost');
        $vend->processVend((int) $s['id']);
        $s = $vend->sale((int) $s['id']);
        $this->assertSame('SUCCEEDED', $s['state']);
        $this->assertSame(1, (int) $this->pdo->query("SELECT COUNT(*) FROM xmlvend_messages WHERE operation='creditvend'")->fetchColumn(), 'sent once, never re-vended');
        $req = $this->pdo->query("SELECT body FROM vend_messages WHERE direction='req' AND operation='creditvend'")->fetchColumn();
        $this->assertStringNotContainsString('sim-password', (string) $req);
    }

    // ------------------------------------------------------------------ helpers

    protected function setUp(): void
    {
        parent::setUp();
        foreach (['bpc_timeout_s' => '2', 'worker_margin_s' => '1', 'advice_first_delay_s' => '1', 'advice_interval_s' => '1', 'advice_window_s' => '6'] as $k => $v) {
            $this->app->settings->apply($k, $v, 'test', $this->app->audit);
        }
    }

    private bool $simReady = false;

    private function requireSim(): void
    {
        if (@file_get_contents(self::SIM . '/_sim/stats') === false) {
            $this->markTestSkipped('BPC simulator not running on :8099 (scripts/demo-up.sh)');
        }
        if (!$this->simReady) {
            $this->post('/_sim/reset', []);
            $this->simReady = true;
        }
    }

    private function provider(string $terminal): XmlVendProvider
    {
        $this->requireSim();
        return new XmlVendProvider($this->app->settings, $this->pdo, new XmlVendConfig('6001234567890', 'maruvend', 'sim-password'), $terminal);
    }

    private function simMode(string $mode): void
    {
        $this->requireSim();
        $this->post('/_sim/mode', ['mode' => $mode, 'count' => 1]);
    }

    private function post(string $path, array $body): void
    {
        $ch = curl_init(self::SIM . $path);
        curl_setopt_array($ch, [CURLOPT_POST => true, CURLOPT_RETURNTRANSFER => true, CURLOPT_POSTFIELDS => json_encode($body)]);
        curl_exec($ch);
    }

    private function dom(string $xml): \DOMDocument
    {
        $d = new \DOMDocument();
        $d->loadXML($xml);
        return $d;
    }

    /** Validate the first element named $local (with its subtree) against the base schema. */
    private function assertSchemaValid(string $xml, string $local): void
    {
        $src = $this->dom($xml);
        $el = (new \DOMXPath($src))->query('//*[local-name()="' . $local . '"]')->item(0);
        $this->assertNotNull($el, "$local not found");
        $doc = new \DOMDocument();
        $doc->appendChild($doc->importNode($el, true));
        $doc->loadXML($doc->saveXML()); // re-parse so in-scope namespaces are declared on the new root
        libxml_use_internal_errors(true);
        $ok = $doc->schemaValidate(__DIR__ . '/fixtures/xmlvend-base-2.0.xsd');
        $errs = array_map(fn ($e) => trim($e->message), libxml_get_errors());
        libxml_clear_errors();
        $this->assertTrue($ok, "$local is not valid against the XMLVend base schema:\n" . implode("\n", $errs));
    }
}
