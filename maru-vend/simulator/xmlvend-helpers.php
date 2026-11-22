<?php
declare(strict_types=1);

/** XML builders for the XMLVend simulator (TEST ONLY). Also used by tests/XmlVendTest.php. */

const XV_SOAP = 'http://schemas.xmlsoap.org/soap/envelope/';
const XV_XSI = 'http://www.w3.org/2001/XMLSchema-instance';

// ------------------------------------------------------------------ helpers

function xv_reply(int $status, string $xml): never
{
    http_response_code($status);
    header('Content-Type: text/xml; charset=utf-8');
    echo $xml;
    exit;
}

function xv_el(DOMDocument $d, string $ns, string $qname, DOMElement $parent): DOMElement
{
    $e = $d->createElementNS($ns, $qname);
    $parent->appendChild($e);
    return $e;
}

/** Envelope + response root with the BaseResp header fields. */
function xv_resp(array $h, string $rootQName, callable $fill): string
{
    $d = new DOMDocument('1.0', 'UTF-8');
    $env = $d->createElementNS(XV_SOAP, 'soap:Envelope');
    $env->setAttributeNS('http://www.w3.org/2000/xmlns/', 'xmlns:xsi', XV_XSI);
    $env->setAttributeNS('http://www.w3.org/2000/xmlns/', 'xmlns:b', $h['baseNs']);
    $env->setAttributeNS('http://www.w3.org/2000/xmlns/', 'xmlns:r', $h['revNs']);
    $d->appendChild($env);
    $body = $d->createElementNS(XV_SOAP, 'soap:Body');
    $env->appendChild($body);
    $root = $d->createElementNS(str_starts_with($rootQName, 'r:') ? $h['revNs'] : $h['baseNs'], $rootQName);
    $body->appendChild($root);
    xv_base_resp($d, $h, $root);
    $fill($d, $root);
    return $d->saveXML();
}

function xv_base_resp(DOMDocument $d, ?array $h, DOMElement $root): void
{
    $b = $h['baseNs'] ?? 'http://www.nrs.eskom.co.za/xmlvend/base/2.1/schema';
    $c = xv_el($d, $b, 'b:clientID', $root);
    $c->setAttributeNS(XV_XSI, 'xsi:type', 'b:EANDeviceID');
    $c->setAttribute('ean', $h['client'] ?? '0000000000000');
    $s = xv_el($d, $b, 'b:serverID', $root);
    $s->setAttributeNS(XV_XSI, 'xsi:type', 'b:EANDeviceID');
    $s->setAttribute('ean', '6004930000001');
    $t = xv_el($d, $b, 'b:terminalID', $root);
    $t->setAttributeNS(XV_XSI, 'xsi:type', 'b:GenericDeviceID');
    $t->setAttribute('id', $h['terminal'] ?? '');
    $m = xv_el($d, $b, 'b:reqMsgID', $root);
    $m->setAttribute('dateTime', $h['dt'] ?? '00000000000000');
    $m->setAttribute('uniqueNumber', (string) ($h['un'] ?? 1));
    xv_el($d, $b, 'b:respDateTime', $root)->textContent = date('c');
}

/** SOAP fault with an XMLVendFaultResp in <detail> (5.2.4.4). */
function xv_fault(string $type, string $desc, ?array $h, ?string $custMsg): string
{
    $b = $h['baseNs'] ?? 'http://www.nrs.eskom.co.za/xmlvend/base/2.1/schema';
    $d = new DOMDocument('1.0', 'UTF-8');
    $env = $d->createElementNS(XV_SOAP, 'soap:Envelope');
    $env->setAttributeNS('http://www.w3.org/2000/xmlns/', 'xmlns:xsi', XV_XSI);
    $env->setAttributeNS('http://www.w3.org/2000/xmlns/', 'xmlns:b', $b);
    $d->appendChild($env);
    $body = $d->createElementNS(XV_SOAP, 'soap:Body');
    $env->appendChild($body);
    $f = $d->createElementNS(XV_SOAP, 'soap:Fault');
    $body->appendChild($f);
    $f->appendChild($d->createElement('faultcode', 'soap:Server'));
    $f->appendChild($d->createElement('faultstring', $desc));
    $detail = $d->createElement('detail');
    $f->appendChild($detail);
    $resp = $d->createElementNS($b, 'b:xmlvendFaultResp');
    $detail->appendChild($resp);
    xv_base_resp($d, $h, $resp);
    if ($custMsg) {
        xv_el($d, $b, 'b:custMsg', $resp)->textContent = $custMsg;
    }
    $fault = xv_el($d, $b, 'b:fault', $resp);
    $fault->setAttributeNS(XV_XSI, 'xsi:type', 'b:' . $type);
    xv_el($d, $b, 'b:desc', $fault)->textContent = $desc;
    return $d->saveXML();
}

/** creditVendResp with CreditVendTx (token), two ServiceChrgTx (fixed charge, levy) and VAT. */
function xv_credit_resp(array $h, array $m, array $req, bool $kct): string
{
    $r = receipt('x', $req['meter'], $req['amount'])['creditVendReceipt'];
    return xv_resp($h, 'r:creditVendResp', function (DOMDocument $d, DOMElement $root) use ($h, $m, $req, $r, $kct) {
        $b = $h['baseNs'];
        $rv = $h['revNs'];
        $cs = xv_el($d, $b, 'b:clientStatus', $root);
        $ac = xv_el($d, $b, 'b:availCredit', $cs);
        $ac->setAttribute('value', '99999.00');
        $ac->setAttribute('symbol', 'BWP');
        $u = xv_el($d, $b, 'b:utility', $root);
        $u->setAttribute('name', 'Botswana Power Corporation');
        $u->setAttribute('address', 'Motlakase House, Gaborone');
        $u->setAttribute('taxRef', 'P00000000000');
        $cvd = xv_el($d, $b, 'b:custVendDetail', $root);
        $cvd->setAttribute('name', $m['name']);
        $cvd->setAttribute('address', 'Gaborone');
        $rc = xv_el($d, $rv, 'r:creditVendReceipt', $root);
        $rc->setAttribute('receiptNo', 'BPC' . random_int(100000, 999999));
        $txs = xv_el($d, $rv, 'r:transactions', $rc);
        $money = function (DOMElement $e, float $v) { $e->setAttribute('value', number_format($v, 2, '.', '')); $e->setAttribute('symbol', 'BWP'); };

        $tx = xv_el($d, $rv, 'r:tx', $txs);
        $tx->setAttributeNS(XV_XSI, 'xsi:type', 'r:CreditVendTx');
        $tx->setAttribute('receiptNo', $rc->getAttribute('receiptNo'));
        $money(xv_el($d, $rv, 'r:amt', $tx), (float) $r['costUnits']);
        $tax = xv_el($d, $rv, 'r:tax', $tx);
        $tax->setAttributeNS(XV_XSI, 'xsi:type', 'b:VAT');
        $tax->setAttribute('rate', '14');
        $money(xv_el($d, $b, 'b:amt', $tax), (float) $r['vat']);
        $cti = xv_el($d, $rv, 'r:creditTokenIssue', $tx);
        $cti->setAttributeNS(XV_XSI, 'xsi:type', 'b:SaleCredTokenIssue');
        xv_el($d, $b, 'b:desc', $cti)->textContent = 'Normal Sale';
        $md = xv_el($d, $b, 'b:meterDetail', $cti);
        foreach (['msno' => $req['meter'], 'sgc' => '600123', 'krn' => $kct ? '2' : '1', 'ti' => $m['ti']] as $k => $v) {
            $md->setAttribute($k, $v);
        }
        $mt = xv_el($d, $b, 'b:meterType', $md);
        $mt->setAttribute('at', '07');
        $mt->setAttribute('tt', '02');
        $tok = xv_el($d, $b, 'b:token', $cti);
        $tok->setAttributeNS(XV_XSI, 'xsi:type', 'b:STS1Token');
        xv_el($d, $b, 'b:stsCipher', $tok)->textContent = $r['stsCipher'];
        $units = xv_el($d, $b, 'b:units', $cti);
        $units->setAttribute('value', (string) $r['tokenUnits']);
        $units->setAttribute('siUnit', 'kWh');
        $res = xv_el($d, $b, 'b:resource', $cti);
        $res->setAttributeNS(XV_XSI, 'xsi:type', 'b:Electricity');

        foreach ([['Fixed Charge', (float) $r['standardCharge']], ['Government Levy', (float) $r['governmentLevy']]] as [$desc, $amt]) {
            if ($amt <= 0) {
                continue;
            }
            $sc = xv_el($d, $rv, 'r:tx', $txs);
            $sc->setAttributeNS(XV_XSI, 'xsi:type', 'r:ServiceChrgTx');
            $money(xv_el($d, $rv, 'r:amt', $sc), $amt);
            xv_el($d, $rv, 'r:desc', $sc)->textContent = $desc;
        }
        if ($kct) {
            $k = xv_el($d, $rv, 'r:tx', $txs);
            $k->setAttributeNS(XV_XSI, 'xsi:type', 'r:KCTx');
            $money(xv_el($d, $rv, 'r:amt', $k), 0);
            $ki = xv_el($d, $rv, 'r:kcTokenIssue', $k);
            $ki->setAttributeNS(XV_XSI, 'xsi:type', 'b:KCTokenIssue');
            xv_el($d, $b, 'b:desc', $ki)->textContent = 'Key Change';
            $kt = xv_el($d, $b, 'b:token', $ki);
            $kt->setAttributeNS(XV_XSI, 'xsi:type', 'b:KCToken');
            foreach (['b:set1stMeterKey', 'b:set2ndMeterKey'] as $q) {
                $s = xv_el($d, $b, $q, $kt);
                $digits = '';
                for ($i = 0; $i < 20; $i++) {
                    $digits .= random_int(0, 9);
                }
                xv_el($d, $b, 'b:stsCipher', $s)->textContent = $digits;
            }
        }
    });
}
