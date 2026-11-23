<?php
declare(strict_types=1);

namespace MaruVend\Provider\XmlVend;

/**
 * Builds and reads XMLVend 2.1 SOAP messages.
 *
 * Structure follows NRS 009-6-10 4.7.3 and the published base schema (types BaseReq, BaseVendReq,
 * MsgID, EANDeviceID, GenericDeviceID, AuthCred, VendIDMethod/MeterNumber, Electricity, Currency,
 * Cash, AdviceReq/LastRespAdviceReq, BaseResp, XMLVendFaultResp, CreditTokenIssue, STS1Token,
 * MeterDetail, VAT, KCTokenIssue/KCToken).
 *
 * Elements declared in the base schema are in the base namespace; elements declared by the
 * revenue schema (the message roots, purchaseValue, confirmCustResult, transactions, ...) are in
 * the revenue namespace (elementFormDefault="qualified"). Polymorphic elements use xsi:type.
 *
 * Reading is namespace-tolerant (matches on local names) so a server using a slightly different
 * namespace version is still understood; writing uses the configured version exactly.
 */
final class XmlVendMessages
{
    private const SOAP = 'http://schemas.xmlsoap.org/soap/envelope/';
    private const XSI = 'http://www.w3.org/2001/XMLSchema-instance';

    // ------------------------------------------------------------------ requests

    public static function confirmCustomerReq(XmlVendConfig $c, string $terminal, array $msgId, string $meter): string
    {
        [$doc, $root] = self::envelope($c, 'confirmCustomerReq');
        self::baseReq($doc, $root, $c, $terminal, $msgId);
        $id = self::b($doc, $c, 'idMethod', $root, 'VendIDMethod');
        self::meter($doc, $c, $id, $meter);
        return $doc->saveXML();
    }

    public static function creditVendReq(XmlVendConfig $c, string $terminal, array $msgId, string $meter, int $amountThebe): string
    {
        [$doc, $root] = self::envelope($c, 'creditVendReq');
        self::baseReq($doc, $root, $c, $terminal, $msgId);
        self::b($doc, $c, 'resource', $root, 'Electricity');
        $id = self::b($doc, $c, 'idMethod', $root, 'VendIDMethod');
        self::meter($doc, $c, $id, $meter);
        $pv = self::r($doc, $c, 'purchaseValue', $root, 'PurchaseValueCurrency');
        $amt = self::r($doc, $c, 'amt', $pv);
        self::money($amt, $amountThebe, $c);
        $pay = self::r($doc, $c, 'payType', $root, 'b:Cash');
        self::money(self::b($doc, $c, 'tenderAmt', $pay), $amountThebe, $c);
        return $doc->saveXML();
    }

    public static function lastRespAdviceReq(XmlVendConfig $c, string $terminal, array $msgId, array $original): string
    {
        $doc = new \DOMDocument('1.0', 'UTF-8');
        $env = $doc->createElementNS(self::SOAP, 'soap:Envelope');
        $env->setAttributeNS('http://www.w3.org/2000/xmlns/', 'xmlns:xsi', self::XSI);
        $env->setAttributeNS('http://www.w3.org/2000/xmlns/', 'xmlns:b', $c->baseNs());
        $doc->appendChild($env);
        $body = $doc->createElementNS(self::SOAP, 'soap:Body');
        $env->appendChild($body);
        $root = $doc->createElementNS($c->baseNs(), 'b:adviceReq');
        $root->setAttributeNS(self::XSI, 'xsi:type', 'b:LastRespAdviceReq');
        $body->appendChild($root);
        self::baseReq($doc, $root, $c, $terminal, $msgId);
        $a = self::b($doc, $c, 'adviceReqMsgID', $root);
        $a->setAttribute('dateTime', $original['dateTime']);
        $a->setAttribute('uniqueNumber', (string) $original['uniqueNumber']);
        return $doc->saveXML();
    }

    // ------------------------------------------------------------------ responses

    /** SOAP fault carrying an XMLVend fault response (5.2.4.4), or null. */
    public static function fault(\DOMDocument $dom): ?array
    {
        $x = new \DOMXPath($dom);
        $resp = $x->query('//*[local-name()="xmlvendFaultResp"]')->item(0);
        $soapFault = $x->query('//*[local-name()="Fault" and namespace-uri()="' . self::SOAP . '"]')->item(0);
        if (!$resp && !$soapFault) {
            return null;
        }
        if (!$resp) {
            return ['type' => 'SOAPFault', 'desc' => trim((string) $x->query('.//*[local-name()="faultstring"]', $soapFault)->item(0)?->textContent)];
        }
        $f = $x->query('.//*[local-name()="fault"]', $resp)->item(0);
        $type = $f instanceof \DOMElement ? $f->getAttributeNS(self::XSI, 'type') : '';
        return [
            'type' => FaultMap::localName($type ?: 'XMLVendFaultEx'),
            'desc' => trim((string) $x->query('.//*[local-name()="desc"]', $f ?? $resp)->item(0)?->textContent),
            'customerMsg' => trim((string) $x->query('./*[local-name()="custMsg"]', $resp)->item(0)?->textContent) ?: null,
        ];
    }

    public static function parseConfirmCustomer(\DOMDocument $dom): array
    {
        $x = new \DOMXPath($dom);
        $cd = $x->query('//*[local-name()="confirmCustResult"]//*[local-name()="custVendDetail"]')->item(0)
            ?? $x->query('//*[local-name()="custVendDetail"]')->item(0);
        $md = $x->query('//*[local-name()="confirmCustResult"]//*[local-name()="meterDetail"]')->item(0);
        $cfg = $x->query('//*[local-name()="custVendConfig"]')->item(0);
        $cur = function (string $name) use ($x, $cfg): ?int {
            $n = $cfg ? $x->query('./*[local-name()="' . $name . '"]', $cfg)->item(0) : null;
            return $n instanceof \DOMElement && $n->hasAttribute('value') ? (int) round(((float) $n->getAttribute('value')) * 100) : null;
        };
        $canVend = $cfg instanceof \DOMElement && $cfg->hasAttribute('canVend') ? !in_array(strtolower($cfg->getAttribute('canVend')), ['false', '0'], true) : null;
        return [
            'name' => $cd instanceof \DOMElement ? $cd->getAttribute('name') : null,
            'address' => $cd instanceof \DOMElement ? $cd->getAttribute('address') : null,
            'msno' => $md instanceof \DOMElement ? $md->getAttribute('msno') : null,
            'ti' => $md instanceof \DOMElement ? $md->getAttribute('ti') : null,
            'canVend' => $canVend,
            'minVendThebe' => $cur('minVendAmt'),
            'maxVendThebe' => $cur('maxVendAmt'),
            'customerMsg' => trim((string) $x->query('//*[local-name()="custMsg"]')->item(0)?->textContent),
        ];
    }

    /** The response wrapped in a LastRespAdviceResp: either a credit vend response or a fault. */
    public static function lastResponseBody(\DOMDocument $dom): ?array
    {
        $x = new \DOMXPath($dom);
        $lr = $x->query('//*[local-name()="lastResponse"]')->item(0);
        if (!$lr instanceof \DOMElement) {
            return null;
        }
        $type = FaultMap::localName($lr->getAttributeNS(self::XSI, 'type'));
        $inner = new \DOMDocument();
        $inner->appendChild($inner->importNode($lr, true));
        if ($type === 'XMLVendFaultResp' || $x->query('.//*[local-name()="fault"]', $lr)->length > 0) {
            $f = $x->query('.//*[local-name()="fault"]', $lr)->item(0);
            return ['type' => 'fault', 'faultType' => FaultMap::localName($f instanceof \DOMElement ? $f->getAttributeNS(self::XSI, 'type') : 'XMLVendFaultEx'),
                'desc' => trim((string) $x->query('.//*[local-name()="desc"]', $lr)->item(0)?->textContent)];
        }
        return ['type' => 'response', 'dom' => $inner];
    }

    /**
     * Read a CreditVendResp (4.7.3.16 figure 62) into the normalised receipt fields.
     * Transactions: CreditVendTx (cost of units, token), ServiceChrgTx (fixed charge, levies),
     * DebtRecoveryTx; taxes (VAT); key change tokens (KCTokenIssue) where the meter's key changed.
     */
    public static function parseCreditVend(\DOMDocument $dom, XmlVendConfig $c): array
    {
        $x = new \DOMXPath($dom);
        $t = fn (?\DOMNode $n) => $n instanceof \DOMElement && $n->hasAttribute('value') ? (int) round(((float) $n->getAttribute('value')) * 100) : 0;
        $type = fn (\DOMElement $e) => FaultMap::localName($e->getAttributeNS(self::XSI, 'type'));

        $out = ['token' => null, 'keyChange1' => null, 'keyChange2' => null, 'kwh' => 0.0, 'costUnitsThebe' => 0, 'fixedChargeThebe' => 0,
            'govLevyThebe' => 0, 'vatThebe' => 0, 'totalThebe' => 0, 'tariffIndex' => null, 'customerName' => null, 'providerRef' => null,
            'unitRateThebe' => null, 'otherChargesThebe' => 0];

        foreach ($x->query('//*[local-name()="tx"]') as $tx) {
            /** @var \DOMElement $tx */
            $amt = $t($x->query('./*[local-name()="amt"]', $tx)->item(0));
            $kind = $type($tx);
            $out['totalThebe'] += $amt;
            foreach ($x->query('./*[local-name()="tax"]', $tx) as $tax) {
                $out['vatThebe'] += $t($x->query('./*[local-name()="amt"]', $tax)->item(0));
            }
            $issue = $x->query('.//*[local-name()="creditTokenIssue"]', $tx)->item(0);
            if ($kind === 'CreditVendTx' || $issue) {
                $out['costUnitsThebe'] += $amt;
                if ($issue instanceof \DOMElement) {
                    $out['token'] = trim((string) $x->query('.//*[local-name()="token"]/*[local-name()="stsCipher"]', $issue)->item(0)?->textContent) ?: null;
                    $u = $x->query('./*[local-name()="units"]', $issue)->item(0);
                    $out['kwh'] += $u instanceof \DOMElement ? (float) $u->getAttribute('value') : 0;
                    $md = $x->query('./*[local-name()="meterDetail"]', $issue)->item(0);
                    if ($md instanceof \DOMElement) {
                        $out['tariffIndex'] = $md->getAttribute('ti') ?: null;
                    }
                }
                if ($r = $tx->getAttribute('receiptNo')) {
                    $out['providerRef'] = $r;
                }
                continue;
            }
            // Service charges and other non-token transactions: classify by description.
            $desc = strtolower(trim((string) ($x->query('./*[local-name()="desc" or local-name()="accDesc"]', $tx)->item(0)?->textContent
                ?? $x->query('.//*[local-name()="tariff"]/*[local-name()="name"]', $tx)->item(0)?->textContent ?? '')) . ' ' . strtolower($kind));
            if (str_contains($desc, 'levy')) {
                $out['govLevyThebe'] += $amt;
            } elseif ($kind === 'ServiceChrgTx' || str_contains($desc, 'fixed') || str_contains($desc, 'service') || str_contains($desc, 'standard')) {
                $out['fixedChargeThebe'] += $amt;
            } else {
                $out['otherChargesThebe'] += $amt;
            }
        }
        // VAT may also be given at receipt level.
        if ($out['vatThebe'] === 0) {
            foreach ($x->query('//*[local-name()="tax"]') as $tax) {
                $out['vatThebe'] += $t($x->query('./*[local-name()="amt"]', $tax)->item(0));
            }
        }
        // Transaction amounts exclude tax: the customer paid the sum of both.
        $out['totalThebe'] += $out['vatThebe'];
        // Key change tokens (meter key revision change): set1stMeterKey, then set2ndMeterKey.
        $kct = $x->query('//*[local-name()="set1stMeterKey"]/*[local-name()="stsCipher"]')->item(0);
        $kct2 = $x->query('//*[local-name()="set2ndMeterKey"]/*[local-name()="stsCipher"]')->item(0);
        $out['keyChange1'] = $kct ? trim($kct->textContent) : null;
        $out['keyChange2'] = $kct2 ? trim($kct2->textContent) : null;

        $cvd = $x->query('//*[local-name()="custVendDetail"]')->item(0);
        $out['customerName'] = $cvd instanceof \DOMElement ? ($cvd->getAttribute('name') ?: null) : null;
        $out['providerRef'] ??= trim((string) $x->query('//*[local-name()="creditVendReceipt"]/@receiptNo | //*[local-name()="receiptNo"]')->item(0)?->textContent) ?: null;
        if ($out['kwh'] > 0 && $out['costUnitsThebe'] > 0) {
            $out['unitRateThebe'] = (int) round($out['costUnitsThebe'] / $out['kwh']);
        }
        if (!$out['token'] || !preg_match('/^\d{20}$/', $out['token'])) {
            throw new \RuntimeException('no valid 20-digit STS token in response');
        }
        return $out;
    }

    /** Remove the password from a request before it is stored. */
    public static function redact(string $xml): string
    {
        return (string) preg_replace('#(<(?:\w+:)?password>)[^<]*(</(?:\w+:)?password>)#', '$1***$2', $xml);
    }

    // ------------------------------------------------------------------ helpers

    private static function envelope(XmlVendConfig $c, string $rootName): array
    {
        $doc = new \DOMDocument('1.0', 'UTF-8');
        $env = $doc->createElementNS(self::SOAP, 'soap:Envelope');
        $env->setAttributeNS('http://www.w3.org/2000/xmlns/', 'xmlns:xsi', self::XSI);
        $env->setAttributeNS('http://www.w3.org/2000/xmlns/', 'xmlns:b', $c->baseNs());
        $env->setAttributeNS('http://www.w3.org/2000/xmlns/', 'xmlns:r', $c->revenueNs());
        $doc->appendChild($env);
        $body = $doc->createElementNS(self::SOAP, 'soap:Body');
        $env->appendChild($body);
        $root = $doc->createElementNS($c->revenueNs(), 'r:' . $rootName);
        $body->appendChild($root);
        return [$doc, $root];
    }

    private static function baseReq(\DOMDocument $doc, \DOMElement $root, XmlVendConfig $c, string $terminal, array $msgId): void
    {
        self::b($doc, $c, 'clientID', $root, 'EANDeviceID')->setAttribute('ean', $c->clientEan);
        self::b($doc, $c, 'terminalID', $root, 'GenericDeviceID')->setAttribute('id', $terminal);
        $m = self::b($doc, $c, 'msgID', $root);
        $m->setAttribute('dateTime', $msgId['dateTime']);
        $m->setAttribute('uniqueNumber', (string) $msgId['uniqueNumber']);
        $auth = self::b($doc, $c, 'authCred', $root);
        self::b($doc, $c, 'opName', $auth)->textContent = $c->opName;
        if ($c->password !== null && $c->password !== '') {
            self::b($doc, $c, 'password', $auth)->textContent = $c->password;
        }
    }

    private static function meter(\DOMDocument $doc, XmlVendConfig $c, \DOMElement $parent, string $meter): void
    {
        self::b($doc, $c, 'meterIdentifier', $parent, 'MeterNumber')->setAttribute('msno', $meter);
    }

    private static function money(\DOMElement $e, int $thebe, XmlVendConfig $c): void
    {
        $e->setAttribute('value', number_format($thebe / 100, 2, '.', ''));
        $e->setAttribute('symbol', $c->currency);
    }

    /** Element in the base namespace, optionally with xsi:type="b:<type>". */
    private static function b(\DOMDocument $doc, XmlVendConfig $c, string $name, \DOMElement $parent, ?string $type = null): \DOMElement
    {
        $e = $doc->createElementNS($c->baseNs(), 'b:' . $name);
        if ($type) {
            $e->setAttributeNS(self::XSI, 'xsi:type', str_contains($type, ':') ? $type : 'b:' . $type);
        }
        $parent->appendChild($e);
        return $e;
    }

    /** Element in the revenue namespace, optionally with xsi:type="r:<type>". */
    private static function r(\DOMDocument $doc, XmlVendConfig $c, string $name, \DOMElement $parent, ?string $type = null): \DOMElement
    {
        $e = $doc->createElementNS($c->revenueNs(), 'r:' . $name);
        if ($type) {
            $e->setAttributeNS(self::XSI, 'xsi:type', str_contains($type, ':') ? $type : 'r:' . $type);
        }
        $parent->appendChild($e);
        return $e;
    }
}
