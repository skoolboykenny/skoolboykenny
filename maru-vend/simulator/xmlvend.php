<?php
declare(strict_types=1);

/**
 * XMLVend 2.1 SOAP endpoint of the BPC simulator (TEST ONLY). Included by simulator/index.php for
 * POST /xmlvend. Shares the fault-injection modes of the REST simulator:
 *
 *   ok          creditVendResp with token, fixed charge, levy and VAT
 *   reject      BlockedMeterEx fault (no token)
 *   processing  SystemEx fault "Security module not responding" (no token)
 *   lost        token issued, response never sent (client times out)
 *   lostfail    nothing issued, response never sent
 *   down        HTTP 503, no body
 *   kct         success with key change tokens (meter moved to a new key revision)
 *
 * Deliberately strict, like the most limited real servers: it keeps only the LAST response per
 * terminal, rejects duplicate msgIDs per client, and answers an advice for any other msgID with
 * LastResponseEx.
 */

/** @var PDO $db */
/** @var array $body unused for SOAP */
$raw = file_get_contents('php://input') ?: '';
$db->exec('CREATE TABLE IF NOT EXISTS xv_msgs (client TEXT, terminal TEXT, dt TEXT, un INTEGER, PRIMARY KEY (client, dt, un))');
$db->exec('CREATE TABLE IF NOT EXISTS xv_last (terminal TEXT PRIMARY KEY, dt TEXT, un INTEGER, response TEXT)');

require_once __DIR__ . '/xmlvend-helpers.php';

$in = new DOMDocument();
if (!@$in->loadXML($raw, LIBXML_NONET)) {
    xv_reply(500, xv_fault('XMLVendSchemaEx', 'Request is not well-formed XML', null, null));
}
$x = new DOMXPath($in);
$root = $x->query('//*[local-name()="Body"]/*')->item(0);
if (!$root instanceof DOMElement) {
    xv_reply(500, xv_fault('XMLVendSchemaEx', 'Empty SOAP body', null, null));
}
$baseNs = $x->query('//*[local-name()="msgID"]')->item(0)?->namespaceURI ?? 'http://www.nrs.eskom.co.za/xmlvend/base/2.1/schema';
$revNs = str_replace('/base/', '/revenue/', $baseNs);
$attr = fn (string $el, string $a) => ($n = $x->query('//*[local-name()="' . $el . '"]')->item(0)) instanceof DOMElement ? $n->getAttribute($a) : '';
$req = [
    'client' => $attr('clientID', 'ean'),
    'terminal' => $attr('terminalID', 'id'),
    'dt' => $attr('msgID', 'dateTime'),
    'un' => (int) $attr('msgID', 'uniqueNumber'),
    'meter' => $attr('meterIdentifier', 'msno'),
    'amount' => (float) $attr('amt', 'value'),
];
$op = $root->localName;
$hdr = compact('baseNs', 'revNs') + $req;

if ($req['client'] === '' || $req['terminal'] === '' || !preg_match('/^\d{14}$/', $req['dt']) || $req['un'] < 1) {
    xv_reply(500, xv_fault('XMLVendSchemaEx', 'clientID, terminalID and msgID are required', $hdr, null));
}
// 5.2.4.3: each msgID must be unique per client.
try {
    $db->prepare('INSERT INTO xv_msgs VALUES (?,?,?,?)')->execute([$req['client'], $req['terminal'], $req['dt'], $req['un']]);
} catch (PDOException) {
    xv_reply(500, xv_fault('XMLVendFaultEx', 'Duplicate message identifier', $hdr, null));
}

hit($db, '/xmlvend/' . $op, 'start');
register_shutdown_function(fn () => hit($db, '/xmlvend/' . $op, 'end'));
usleep(300_000);

if ($op === 'confirmCustomerReq') {
    $m = METERS[$req['meter']] ?? null;
    if (!$m) {
        xv_reply(500, xv_fault('UnknownMeterEx', 'Meter not found', $hdr, 'The meter number is not registered with BPC.'));
    }
    $resp = xv_resp($hdr, 'r:confirmCustomerResp', function (DOMDocument $d, DOMElement $r) use ($m, $req, $hdr) {
        $res = xv_el($d, $hdr['revNs'], 'r:confirmCustResult', $r);
        $cvd = xv_el($d, $hdr['baseNs'], 'b:custVendDetail', $res);
        $cvd->setAttribute('name', $m['name']);
        $cvd->setAttribute('address', 'Gaborone');
        $md = xv_el($d, $hdr['baseNs'], 'b:meterDetail', $res);
        foreach (['msno' => $req['meter'], 'sgc' => '600123', 'krn' => '1', 'ti' => $m['ti']] as $k => $v) {
            $md->setAttribute($k, $v);
        }
        $mt = xv_el($d, $hdr['baseNs'], 'b:meterType', $md);
        $mt->setAttribute('at', '07');
        $mt->setAttribute('tt', '02');
        $cfg = xv_el($d, $hdr['revNs'], 'r:custVendConfig', $res);
        $cfg->setAttribute('canVend', empty($m['blocked']) ? 'true' : 'false');
        $min = xv_el($d, $hdr['revNs'], 'r:minVendAmt', $cfg);
        $min->setAttribute('value', '10.00');
        $min->setAttribute('symbol', 'BWP');
    });
    xv_reply(200, $resp);
}

if ($op === 'creditVendReq') {
    $db->beginTransaction();
    $mrow = $db->query('SELECT * FROM mode WHERE id = 1')->fetch();
    $mode = $mrow['remaining'] > 0 ? $mrow['mode'] : 'ok';
    if ($mrow['remaining'] > 0) {
        $db->exec('UPDATE mode SET remaining = remaining - 1 WHERE id = 1');
    }
    $db->commit();
    $m = METERS[$req['meter']] ?? null;
    if (!$m) {
        $mode = 'unknown';
    } elseif (!empty($m['blocked'])) {
        $mode = 'reject';
    }
    $store = fn (string $xml) => $db->prepare('INSERT OR REPLACE INTO xv_last VALUES (?,?,?,?)')->execute([$req['terminal'], $req['dt'], $req['un'], $xml]);
    switch ($mode) {
        case 'unknown':
            $f = xv_fault('UnknownMeterEx', 'Meter not found', $hdr, 'The meter number is not registered with BPC.');
            $store($f);
            xv_reply(500, $f);
        case 'reject':
            $f = xv_fault('BlockedMeterEx', 'Meter is blocked', $hdr, 'This meter is blocked. Please contact BPC.');
            $store($f);
            xv_reply(500, $f);
        case 'processing':
            $f = xv_fault('SystemEx', 'Security module not responding. Please try later.', $hdr, 'BPC is busy. Please try again shortly.');
            $store($f);
            xv_reply(500, $f);
        case 'down':
            http_response_code(503);
            exit;
        case 'lostfail':
            $db->prepare('DELETE FROM xv_last WHERE terminal = ?')->execute([$req['terminal']]);
            sleep(60);
            exit;
        default:
            $ok = xv_credit_resp($hdr, $m, $req, $mode === 'kct');
            $store($ok);
            if ($mode === 'lost') {
                sleep(60);
                exit;
            }
            xv_reply(200, $ok);
    }
}

if ($op === 'adviceReq') {
    $want = [$attr('adviceReqMsgID', 'dateTime'), (int) $attr('adviceReqMsgID', 'uniqueNumber')];
    $st = $db->prepare('SELECT * FROM xv_last WHERE terminal = ?');
    $st->execute([$req['terminal']]);
    $last = $st->fetch();
    if (!$last || $last['dt'] !== $want[0] || (int) $last['un'] !== $want[1]) {
        xv_reply(500, xv_fault('LastResponseEx', 'No response held for that request: it was not processed', $hdr, null));
    }
    $inner = new DOMDocument();
    $inner->loadXML($last['response']);
    $innerRoot = (new DOMXPath($inner))->query('//*[local-name()="Body"]/*')->item(0)
        ?? (new DOMXPath($inner))->query('//*[local-name()="detail"]/*')->item(0);
    $resp = xv_resp($hdr, 'b:adviceResp', function (DOMDocument $d, DOMElement $r) use ($hdr, $innerRoot, $want) {
        $r->setAttributeNS(XV_XSI, 'xsi:type', 'b:LastRespAdviceResp');
        $a = xv_el($d, $hdr['baseNs'], 'b:adviceReqMsgID', $r);
        $a->setAttribute('dateTime', $want[0]);
        $a->setAttribute('uniqueNumber', (string) $want[1]);
        $lr = xv_el($d, $hdr['baseNs'], 'b:lastResponse', $r);
        $isFault = $innerRoot->localName === 'xmlvendFaultResp';
        $lr->setAttributeNS(XV_XSI, 'xsi:type', $isFault ? 'b:XMLVendFaultResp' : 'r:CreditVendResp');
        foreach (iterator_to_array($innerRoot->childNodes) as $c) {
            $lr->appendChild($d->importNode($c, true));
        }
    });
    xv_reply(200, $resp);
}

xv_reply(500, xv_fault('UseCaseSupportEx', "Operation $op is not supported", $hdr, null));

