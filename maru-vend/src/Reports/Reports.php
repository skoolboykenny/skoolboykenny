<?php
declare(strict_types=1);

namespace MaruVend\Reports;

use MaruVend\Settings;
use PDO;

/**
 * BPC reports (Scope 3e, Deliverable 4e, Annexure 3, tender 2.3(i)).
 * All amounts are returned in Pula with two decimals; stored values are integer thebe.
 */
final class Reports
{
    public function __construct(private PDO $pdo, private Settings $settings) {}

    /** Annexure 3 sales report for successful sales in [from, to). */
    public function sales(string $from, string $to, array $filters = []): array
    {
        [$where, $params] = $this->filters($filters);
        $st = $this->pdo->prepare("SELECT s.receipt_no, t.issued_at, s.meter_number, s.amount_thebe, t.kwh, t.token, t.key_change_1, t.key_change_2,
                t.vat_thebe, s.customer_name, t.gov_levy_thebe, t.fixed_charge_thebe, t.cost_units_thebe, t.unit_rate_thebe,
                t.total_thebe, t.tariff_index, c.type AS channel, m.code AS merchant
            FROM vend_sales s JOIN vend_tokens t ON t.sale_id = s.id
            JOIN channels c ON c.id = s.channel_id JOIN merchants m ON m.id = s.merchant_id
            WHERE t.issued_at >= ? AND t.issued_at < ? $where ORDER BY t.issued_at");
        $st->execute(array_merge([$from, $to], $params));
        $vatNo = $this->settings->get('bpc_vat_no');
        return array_map(fn ($r) => [
            'BPC VAT number' => $vatNo,
            'Receipt/Transaction number' => $r['receipt_no'],
            'Date and time of transaction' => substr((string) $r['issued_at'], 0, 19),
            'Meter number' => $r['meter_number'],
            'Transaction amount tendered' => self::p($r['amount_thebe']),
            'kWh/Units issued' => number_format((float) $r['kwh'], 1, '.', ''),
            'Token number' => self::token($r['token']),
            'Key change tokens' => trim(self::token($r['key_change_1']) . ' ' . self::token($r['key_change_2'])),
            'VAT' => self::p($r['vat_thebe']),
            'Customer name' => $r['customer_name'],
            'Government levy' => self::p($r['gov_levy_thebe']),
            'Fixed charge' => self::p($r['fixed_charge_thebe']),
            'Cost of units' => self::p($r['cost_units_thebe']),
            'Unit cost' => $r['unit_rate_thebe'] !== null ? self::p($r['unit_rate_thebe']) : ($r['kwh'] > 0 ? number_format($r['cost_units_thebe'] / 100 / $r['kwh'], 4, '.', '') : ''),
            'Total amount' => self::p($r['total_thebe']),
            'Tariff index' => $r['tariff_index'],
            'Channel' => $r['channel'],
            'Merchant' => $r['merchant'],
        ], $st->fetchAll());
    }

    /**
     * Every sale and its state exactly as it stood at $asOf, rebuilt from the append-only
     * sale_events history (tender 2.3(i)(ii)). Later changes do not alter this report.
     */
    public function pointInTime(string $asOf): array
    {
        $st = $this->pdo->prepare('SELECT s.receipt_no, s.meter_number, s.amount_thebe, s.customer_name, e.to_state, e.at, e.cause
            FROM sale_events e
            JOIN (SELECT sale_id, MAX(seq) seq FROM sale_events WHERE at <= ? GROUP BY sale_id) last
              ON last.sale_id = e.sale_id AND last.seq = e.seq
            JOIN vend_sales s ON s.id = e.sale_id
            ORDER BY s.id');
        $st->execute([$asOf]);
        return array_map(fn ($r) => [
            'As at' => $asOf,
            'Receipt/Transaction number' => $r['receipt_no'],
            'Meter number' => $r['meter_number'],
            'Customer name' => $r['customer_name'],
            'Amount' => self::p($r['amount_thebe']),
            'Status at that time' => $r['to_state'],
            'Status since' => substr((string) $r['at'], 0, 19),
            'Last event' => $r['cause'],
        ], $st->fetchAll());
    }

    /** Service fee invoice for a period (Scope 5.1: 5% of face value). */
    public function serviceFeeInvoice(string $from, string $to): array
    {
        $st = $this->pdo->prepare("SELECT COUNT(*) n, COALESCE(SUM(s.amount_thebe),0) face, COALESCE(SUM(l.amount_thebe),0) fee
            FROM float_ledger l JOIN vend_sales s ON s.id = l.sale_id
            WHERE l.entry_type = 'fee' AND l.created_at >= ? AND l.created_at < ?");
        $st->execute([$from, $to]);
        $r = $st->fetch();
        return [
            'Invoice number' => 'MQ-SF-' . date('Ym', strtotime($from)),
            'Billed to' => 'Botswana Power Corporation',
            'Period' => "$from to $to",
            'Transactions' => (int) $r['n'],
            'Face value of sales' => self::p($r['face']),
            'Service fee rate' => ($this->settings->int('service_fee_bp') / 100) . '%',
            'Service fee due' => self::p($r['fee']),
        ];
    }

    /** Daily or monthly reconciliation (Annexure 3, 1.3). */
    public function reconciliation(string $from, string $to): array
    {
        $q = fn (string $sql) => (function () use ($sql, $from, $to) {
            $st = $this->pdo->prepare($sql);
            $st->execute([$from, $to]);
            return (int) $st->fetchColumn();
        })();
        $sales = $q("SELECT COALESCE(SUM(amount_thebe),0) FROM float_ledger WHERE entry_type='settle' AND created_at >= ? AND created_at < ?");
        $deposits = $q('SELECT COALESCE(SUM(amount_thebe),0) FROM bpc_deposits WHERE deposited_at >= ? AND deposited_at < ?');
        $refunds = $q("SELECT COALESCE(SUM(amount_thebe),0) FROM float_ledger WHERE entry_type='release' AND created_at >= ? AND created_at < ?");
        $fee = $q("SELECT COALESCE(SUM(amount_thebe),0) FROM float_ledger WHERE entry_type='fee' AND created_at >= ? AND created_at < ?");
        $unresolved = (int) $this->pdo->query("SELECT COALESCE(SUM(amount_thebe),0) FROM vend_sales WHERE state IN ('UNKNOWN','MANUAL_REVIEW')")->fetchColumn();
        $pos = $this->pdo->query('SELECT available, reserved FROM float_position WHERE id = 1')->fetch() ?: ['available' => 0, 'reserved' => 0];
        return [
            'Period' => "$from to $to",
            'Sales (tokens issued)' => self::p($sales),
            'Cash deposited with BPC' => self::p($deposits),
            'Refunds (sales failed at BPC, customer not charged)' => self::p($refunds),
            'Service fee earned (owing from BPC)' => self::p($fee),
            'Held in unresolved sales (awaiting BPC confirmation)' => self::p($unresolved),
            'Float available now' => self::p($pos['available']),
            'Float reserved now' => self::p($pos['reserved']),
        ];
    }

    public static function toCsv(array $rows): string
    {
        if (!$rows) {
            return '';
        }
        $rows = array_is_list($rows) ? $rows : [$rows];
        $h = fopen('php://temp', 'r+');
        fputcsv($h, array_keys($rows[0]), ',', '"', '');
        foreach ($rows as $r) {
            fputcsv($h, array_values($r), ',', '"', '');
        }
        rewind($h);
        return stream_get_contents($h);
    }

    private function filters(array $f): array
    {
        $where = '';
        $p = [];
        foreach (['channel' => 'c.type', 'merchant' => 'm.code', 'meter' => 's.meter_number'] as $k => $col) {
            if (!empty($f[$k])) {
                $where .= " AND $col = ?";
                $p[] = $f[$k];
            }
        }
        if (!empty($f['area'])) {
            $where .= ' AND m.area_id = ?';
            $p[] = (int) $f['area'];
        }
        return [$where, $p];
    }

    private static function p(int|string|null $thebe): string
    {
        return number_format(((int) $thebe) / 100, 2, '.', '');
    }

    private static function token(?string $t): string
    {
        return $t ? trim(chunk_split($t, 4, ' ')) : '';
    }
}
