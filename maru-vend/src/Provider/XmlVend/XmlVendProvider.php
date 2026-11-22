<?php
declare(strict_types=1);

namespace MaruVend\Provider\XmlVend;

use MaruVend\Db;
use MaruVend\Provider\ProviderResult;
use MaruVend\Provider\VendProvider;
use MaruVend\Settings;
use PDO;

/**
 * XMLVend 2.1 client for BPC's CONLOG vending server (clause 7.1), built from the public
 * specification NRS 009-6-10:2010 and the published XMLVend base schema.
 *
 * Transport (5.2.4): SOAP 1.1 over HTTPS, synchronous request/response, SOAPAction "" ,
 * mutual TLS (5.2.6.2.3.3), inside the IPsec tunnel. Timeouts follow BPC's setting (clause 7.8).
 *
 * Messages used:
 *   confirmCustomerReq    meter and customer check, no money (4.7.3.3)
 *   creditVendReq         buy the token; final (4.7.3.16)
 *   adviceReq (LastRespAdviceReq)  recover the outcome of an uncertain credit vend (4.5.4.2 c)
 *
 * Recovery uses "advise last response" only: the lowest-risk advice mechanism (4.5.4.2), the
 * server never depends on the client and reversals are never sent.
 *
 * Message identity (5.2.4.3): every request carries msgID = dateTime (14 digits) + uniqueNumber
 * (up to 6 digits), unique per client. A msgID is allocated and stored in xmlvend_messages BEFORE
 * the request is sent, so an advice can always name the exact request. Each worker uses its own
 * terminal ID, and if a credit vend's outcome is uncertain the worker resolves it with advice
 * before sending anything else from that terminal (4.5.4.2: "locking ... until the exception
 * scenario has been resolved"). Servers that only keep the last response per terminal therefore
 * still answer correctly. If the terminal has sent other requests since, a LastResponseEx is NOT
 * treated as "never processed": the sale is held for manual reconciliation instead.
 *
 * Element names and namespaces of the revenue messages follow the NRS 009-6-10 class diagrams
 * and the naming of the base schema; they must be checked against the revenue XSD and WSDL BPC
 * supplies (5.2.2.1 says the schemas are definitive). They are isolated in XmlVendMessages.
 */
final class XmlVendProvider implements VendProvider
{
    public function __construct(
        private Settings $settings,
        private PDO $pdo,
        private XmlVendConfig $cfg,
        private string $terminalId,
        private ?\Closure $sleep = null,
    ) {}

    public function name(): string
    {
        return 'xmlvend';
    }

    public function confirmCustomer(string $clientSaleId, string $meter, int $amountThebe, string $terminal): ProviderResult
    {
        $msgId = $this->allocateMsgId($clientSaleId, 'confirm');
        $xml = XmlVendMessages::confirmCustomerReq($this->cfg, $this->terminalId, $msgId, $meter);
        $r = $this->send($xml, 'confirm');
        if ($r->outcome !== ProviderResult::OK) {
            // A confirm issues nothing: any uncertainty is simply "could not confirm".
            return $r->outcome === ProviderResult::UNKNOWN
                ? new ProviderResult(ProviderResult::SYSTEM_FAULT, [], $r->faultCode, 'Could not confirm meter in time', exchange: $r->exchange)
                : $r;
        }
        $d = XmlVendMessages::parseConfirmCustomer($r->data['dom']);
        if ($d['canVend'] === false) {
            return new ProviderResult(ProviderResult::BUSINESS_FAULT, [], 'canVend=false', $d['customerMsg'] ?: 'This meter cannot be vended to.', exchange: $r->exchange);
        }
        foreach (['minVendThebe' => 'below the minimum', 'maxVendThebe' => 'above the maximum'] as $k => $why) {
            if ($d[$k] !== null && (($k === 'minVendThebe' && $amountThebe < $d[$k]) || ($k === 'maxVendThebe' && $amountThebe > $d[$k]))) {
                return new ProviderResult(ProviderResult::BUSINESS_FAULT, [], 'amount', sprintf('Amount is %s allowed for this meter (P%.2f).', $why, $d[$k] / 100), exchange: $r->exchange);
            }
        }
        return new ProviderResult(ProviderResult::OK, ['customerName' => $d['name'], 'meterNumber' => $d['msno'] ?? $meter], exchange: $r->exchange);
    }

    public function creditVend(string $clientSaleId, string $meter, int $amountThebe, string $terminal): ProviderResult
    {
        // A new msgID per attempt: a retry only ever follows a definitive "not processed".
        $msgId = $this->allocateMsgId($clientSaleId, 'creditvend', $meter);
        $xml = XmlVendMessages::creditVendReq($this->cfg, $this->terminalId, $msgId, $meter, $amountThebe);
        $r = $this->send($xml, 'creditvend');
        if ($r->outcome === ProviderResult::OK) {
            return $this->receipt($r);
        }
        if ($r->outcome !== ProviderResult::UNKNOWN) {
            return $r;
        }
        // Uncertain: resolve on this terminal now, before it sends anything else.
        $deadline = time() + $this->settings->int('advice_window_s');
        $wait = $this->settings->int('advice_first_delay_s');
        $last = $r;
        while (time() + $wait <= $deadline) {
            ($this->sleep ?? fn (int $s) => sleep($s))($wait);
            $a = $this->lastResponse($clientSaleId);
            if (in_array($a->outcome, [ProviderResult::OK, ProviderResult::BUSINESS_FAULT, ProviderResult::NOT_FOUND], true)) {
                return $a;
            }
            $last = $a;
            $wait = $this->settings->int('advice_interval_s');
        }
        return new ProviderResult(ProviderResult::UNKNOWN, [], $last->faultCode ?? $r->faultCode,
            'No answer from BPC within the advice window', exchange: $r->exchange);
    }

    public function lastResponse(string $clientSaleId): ProviderResult
    {
        $st = $this->pdo->prepare("SELECT * FROM xmlvend_messages WHERE client_sale_id = ? AND operation = 'creditvend' ORDER BY id DESC LIMIT 1");
        $st->execute([$clientSaleId]);
        $orig = $st->fetch();
        if (!$orig) {
            // We never allocated a msgID, so nothing was ever sent for this sale.
            return new ProviderResult(ProviderResult::NOT_FOUND, [], 'NO_REQUEST', 'No credit vend was sent for this sale');
        }
        $adviceMsgId = $this->allocateMsgId($clientSaleId, 'advice', null, $orig['terminal_id']);
        $xml = XmlVendMessages::lastRespAdviceReq($this->cfg, $orig['terminal_id'], $adviceMsgId,
            ['dateTime' => $orig['msg_datetime'], 'uniqueNumber' => (int) $orig['msg_unique']]);
        $r = $this->send($xml, 'advice');

        if ($r->outcome === ProviderResult::OK) {
            $inner = XmlVendMessages::lastResponseBody($r->data['dom']);
            if ($inner === null) {
                return new ProviderResult(ProviderResult::PENDING, [], 'NO_LAST_RESPONSE', 'Advice response carried no last response', exchange: $r->exchange);
            }
            if ($inner['type'] === 'fault') {
                // The original request was answered with a fault: map it as if received first time.
                return $this->faultResult($inner['faultType'], $inner['desc'], 'creditvend', $r->exchange);
            }
            return $this->receipt(new ProviderResult(ProviderResult::OK, ['dom' => $inner['dom']], exchange: $r->exchange));
        }

        if ($r->outcome === ProviderResult::NOT_FOUND) {
            // LastResponseEx means "not processed, the client can safely repeat" (4.6.2.2), but only
            // if the server's "last response" for this terminal really refers to our request.
            $later = $this->pdo->prepare("SELECT COUNT(*) FROM xmlvend_messages WHERE terminal_id = ? AND id > ? AND operation <> 'advice'");
            $later->execute([$orig['terminal_id'], $orig['id']]);
            if ((int) $later->fetchColumn() > 0) {
                return new ProviderResult(ProviderResult::PENDING, [], 'LastResponseEx-AMBIGUOUS',
                    'Terminal sent other requests since; reconcile this sale with BPC records', exchange: $r->exchange);
            }
        }
        return $r;
    }

    // ------------------------------------------------------------------ internals

    /** Allocate the next msgID for this terminal and store it before anything is sent. */
    private function allocateMsgId(string $clientSaleId, string $op, ?string $meter = null, ?string $terminal = null): array
    {
        $terminal ??= $this->terminalId;
        return Db::tx($this->pdo, function (PDO $pdo) use ($clientSaleId, $op, $terminal) {
            $dt = (new \DateTimeImmutable('now', new \DateTimeZone('Africa/Gaborone')))->format('YmdHis');
            $pdo->prepare('INSERT INTO xmlvend_messages (client_sale_id, operation, terminal_id, msg_datetime, msg_unique) VALUES (?,?,?,?,0)')
                ->execute([$clientSaleId, $op, $terminal, $dt]);
            $id = (int) $pdo->lastInsertId();
            $unique = ($id % 999999) + 1; // 1..999999 (6 digits, positiveInteger)
            $pdo->prepare('UPDATE xmlvend_messages SET msg_unique = ? WHERE id = ?')->execute([$unique, $id]);
            return ['dateTime' => $dt, 'uniqueNumber' => $unique];
        });
    }

    private function receipt(ProviderResult $r): ProviderResult
    {
        try {
            $d = XmlVendMessages::parseCreditVend($r->data['dom'], $this->cfg);
        } catch (\Throwable $e) {
            // We cannot read the token: the sale may well have succeeded. Never fail it; recover it.
            return new ProviderResult(ProviderResult::UNKNOWN, [], 'PARSE', 'Credit vend response could not be read: ' . $e->getMessage(), exchange: $r->exchange);
        }
        return new ProviderResult(ProviderResult::OK, $d, exchange: $r->exchange);
    }

    private function send(string $xml, string $op): ProviderResult
    {
        $url = rtrim($this->settings->endpoint(), '/') . $this->cfg->path; // re-read every call (clause 7.11)
        $ch = curl_init($url);
        $opts = [
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => $xml,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_HTTPHEADER => ['Content-Type: text/xml; charset=utf-8', 'SOAPAction: ""'],
            CURLOPT_ENCODING => 'gzip',                       // 5.2.5: optional HTTP gzip
            CURLOPT_CONNECTTIMEOUT => 10,
            CURLOPT_TIMEOUT => $this->settings->workerTimeout(), // mapped to BPC's timeout (clause 7.8)
            CURLOPT_SSL_VERIFYPEER => true,
            CURLOPT_SSL_VERIFYHOST => 2,
            CURLOPT_SSLVERSION => CURL_SSLVERSION_TLSv1_2,
        ];
        if ($this->cfg->clientCert) { // mutual TLS (5.2.6.2.3.3)
            $opts[CURLOPT_SSLCERT] = $this->cfg->clientCert;
            $opts[CURLOPT_SSLKEY] = $this->cfg->clientKey;
        }
        if ($this->cfg->caFile) {
            $opts[CURLOPT_CAINFO] = $this->cfg->caFile;
        }
        curl_setopt_array($ch, $opts);
        $raw = curl_exec($ch);
        $errno = curl_errno($ch);
        $http = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        $err = curl_error($ch);
        curl_close($ch);
        $exchange = ['request' => XmlVendMessages::redact($xml), 'response' => is_string($raw) ? $raw : "curl error $errno: $err", 'http' => $http, 'path' => $op];

        if ($raw === false || $raw === '') {
            $neverSent = in_array($errno, [CURLE_COULDNT_CONNECT, CURLE_COULDNT_RESOLVE_HOST, CURLE_SSL_CONNECT_ERROR, 60, 58], true);
            return new ProviderResult($neverSent || $op !== 'creditvend' ? ProviderResult::SYSTEM_FAULT : ProviderResult::UNKNOWN,
                [], "CURL$errno", $err ?: 'Empty response', exchange: $exchange);
        }
        $dom = new \DOMDocument();
        // No network access and no entity substitution while parsing (XXE-safe).
        if (!@$dom->loadXML($raw, LIBXML_NONET)) {
            return new ProviderResult($op === 'creditvend' ? ProviderResult::UNKNOWN : ProviderResult::SYSTEM_FAULT, [], "HTTP$http", 'Response is not XML', exchange: $exchange);
        }
        $fault = XmlVendMessages::fault($dom);
        if ($fault !== null) {
            return $this->faultResult($fault['type'], $fault['desc'], $op, $exchange, $fault['customerMsg'] ?? null);
        }
        if ($http !== 200) {
            return new ProviderResult($op === 'creditvend' ? ProviderResult::UNKNOWN : ProviderResult::SYSTEM_FAULT, [], "HTTP$http", 'Unexpected HTTP status', exchange: $exchange);
        }
        return new ProviderResult(ProviderResult::OK, ['dom' => $dom], exchange: $exchange);
    }

    /** Map an XMLVend fault (4.6.3, 4.7.3.9) to an outcome. Annex E documents this table. */
    private function faultResult(string $type, string $desc, string $op, array $exchange, ?string $customerMsg = null): ProviderResult
    {
        $outcome = FaultMap::outcome($type, $op);
        return new ProviderResult($outcome, [], $type, $customerMsg ?: $desc, exchange: $exchange);
    }
}
