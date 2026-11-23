<?php
declare(strict_types=1);

namespace MaruVend\Dashboard;

use MaruVend\App;
use PDO;

/**
 * Live figures for the operations dashboard (GET /bpc/api/overview). Read-only queries; amounts
 * in thebe. The shape matches the `D` object the page renders.
 */
final class OpsOverview
{
    private const CHANNEL_KEYS = ['WEB' => 'web', 'APP' => 'app', 'POS' => 'pos', 'USSD' => 'ussd'];

    /** Measured on the sample stack; shown labelled as such until live BPC figures exist. */
    private const MEASURED = ['p95' => '0.80 s', 'lostRecovered' => '9.3–9.9 s', 'crashRecovery' => '11.2 s',
        'note' => 'Timings measured on the sample stack, 22 Nov 2026 (simulator, 200 sales).'];

    public static function build(App $app, array $user): array
    {
        $pdo = $app->pdo;
        $f = $app->float()->position();
        $set = $app->settings;

        $today = $pdo->query("SELECT
                COUNT(*) AS n,
                COALESCE(SUM(state = 'SUCCEEDED'), 0) AS succeeded,
                COALESCE(SUM(state = 'FAILED'), 0) AS failed,
                COALESCE(SUM(CASE WHEN state = 'SUCCEEDED' THEN amount_thebe END), 0) AS value
            FROM vend_sales WHERE created_at >= CURDATE()")->fetch();
        $issued = (int) $pdo->query("SELECT COUNT(*) FROM vend_tokens t JOIN vend_sales s ON s.id = t.sale_id WHERE s.created_at >= CURDATE()")->fetchColumn();
        // Integrity checks over all time: a success with no token, and a token issued twice.
        $lost = (int) $pdo->query("SELECT COUNT(*) FROM vend_sales s LEFT JOIN vend_tokens t ON t.sale_id = s.id WHERE s.state = 'SUCCEEDED' AND t.sale_id IS NULL")->fetchColumn();
        $dupes = (int) $pdo->query('SELECT COUNT(*) FROM (SELECT token FROM vend_tokens GROUP BY token HAVING COUNT(*) > 1) d')->fetchColumn();

        $counts = $pdo->query("SELECT state, COUNT(*) FROM vend_sales WHERE created_at >= CURDATE() GROUP BY state")->fetchAll(PDO::FETCH_KEY_PAIR);
        // Uncertain and review states are shown whenever they are open, not only if created today.
        foreach ($pdo->query("SELECT state, COUNT(*) FROM vend_sales WHERE state IN ('UNKNOWN','MANUAL_REVIEW','SUBMITTED','RESERVED') GROUP BY state")->fetchAll(PDO::FETCH_KEY_PAIR) as $k => $v) {
            $counts[$k] = (int) $v;
        }
        $states = [];
        foreach ([['SUCCEEDED', 'good', 0], ['SUBMITTED', 'info', 0], ['RESERVED', 'info', 0], ['UNKNOWN', 'warn', 1],
                  ['MANUAL_REVIEW', 'bad', 1], ['FAILED', 'bad', 1], ['EXPIRED', 'mute', 1]] as [$k, $tone, $side]) {
            $states[] = ['k' => $k, 'n' => (int) ($counts[$k] ?? 0), 'tone' => $tone, 'side' => $side];
        }
        $inflightOld = (int) $pdo->query("SELECT COUNT(*) FROM vend_sales WHERE state = 'SUBMITTED' AND submitted_at < NOW(6) - INTERVAL 30 SECOND")->fetchColumn();

        $attention = [];
        $rows = $pdo->query("SELECT s.id, s.state, s.receipt_no, s.meter_number, s.amount_thebe, c.type, s.fault_code,
                TIMESTAMPDIFF(SECOND, COALESCE(s.submitted_at, s.created_at), NOW()) AS age,
                (SELECT e.cause FROM sale_events e WHERE e.sale_id = s.id ORDER BY e.seq DESC LIMIT 1) AS why
            FROM vend_sales s JOIN channels c ON c.id = s.channel_id
            WHERE s.state IN ('UNKNOWN','MANUAL_REVIEW') OR (s.state = 'FAILED' AND s.created_at >= CURDATE())
            ORDER BY FIELD(s.state, 'MANUAL_REVIEW', 'UNKNOWN', 'FAILED'), s.created_at LIMIT 8")->fetchAll();
        foreach ($rows as $r) {
            $attention[] = ['id' => (int) $r['id'], 'st' => $r['state'], 'receipt' => $r['receipt_no'] ?: ('#' . $r['id']),
                'meter' => $r['meter_number'], 'amt' => (int) $r['amount_thebe'], 'ch' => self::channelName($r['type']),
                'age' => self::age((int) $r['age']), 'why' => (string) ($r['why'] ?? $r['fault_code'] ?? '')];
        }

        return [
            'live' => true,
            'generatedAt' => date('H:i:s'),
            'user' => ['name' => $user['username'], 'role' => $user['role'], 'viewer' => $user['role'] === 'bpc_viewer'],
            'float' => ['available' => $f['available'], 'reserved' => $f['reserved'], 'lastDeposit' => $f['last_deposit_thebe'],
                'alertPct' => $set->int('float_alert_pct')],
            'today' => ['value' => (int) $today['value'], 'count' => (int) $today['n'], 'succeeded' => (int) $today['succeeded'],
                'issued' => $issued, 'failed' => (int) $today['failed']],
            'integrity' => ['lost' => $lost, 'dupes' => $dupes, 'reconciled' => self::lastReconciliation($pdo)],
            'states' => $states,
            'inflightOld' => $inflightOld,
            'attention' => $attention,
            'channels' => [
                'today' => self::series($pdo, "DATE_FORMAT(s.created_at, '%H:00')", 'CURDATE()', 'today'),
                'd7' => self::series($pdo, "DATE_FORMAT(s.created_at, '%a %d')", 'CURDATE() - INTERVAL 6 DAY', '7 days'),
                'd30' => self::series($pdo, "CONCAT('Wk ', DATE_FORMAT(s.created_at, '%v'))", 'CURDATE() - INTERVAL 29 DAY', '30 days'),
            ],
            'link' => [
                'provider' => $set->get('provider'),
                'endpoint' => $set->get('endpoint_active') === 'backup' ? 'Backup' : 'Primary',
                'site' => ucfirst($set->get('active_site')),
                'rate' => $set->int('rate_per_s') . ' / s',
                'terminals' => self::terminals($pdo),
                'measured' => self::MEASURED,
            ],
            'workers' => self::workers($pdo),
            'districts' => array_map(fn ($d) => ['n' => $d['village'] . ' · ' . $d['district'], 's' => ucfirst($d['status'])],
                $pdo->query('SELECT district, village, status FROM designated_areas ORDER BY status = "live" DESC, id')->fetchAll()),
            'audit' => array_map(fn ($a) => ['t' => substr($a['created_at'], 11, 5), 'a' => $a['actor'],
                    'w' => $a['action'] . ($a['entity_id'] ? ' · ' . $a['entity'] . ' ' . $a['entity_id'] : ''),
                    'v' => $a['new_value'] !== null ? mb_strimwidth((string) $a['new_value'], 0, 60, '…') : null],
                $pdo->query('SELECT created_at, actor, action, entity, entity_id, new_value FROM audit_log ORDER BY id DESC LIMIT 6')->fetchAll()),
            'ledger' => array_map(fn ($l) => ['t' => substr($l['created_at'], 11, 5),
                    'w' => self::ledgerLabel($l['entry_type']) . ($l['receipt_no'] ? ' ' . $l['receipt_no'] : ''),
                    // reserve and release change available float; settle and fee only move it between columns
                    'v' => (int) $l['amount_thebe'], 'neutral' => in_array($l['entry_type'], ['settle', 'fee'], true)],
                $pdo->query('SELECT l.created_at, l.entry_type, l.amount_thebe, s.receipt_no FROM float_ledger l
                    LEFT JOIN vend_sales s ON s.id = l.sale_id ORDER BY l.id DESC LIMIT 6')->fetchAll()),
        ];
    }

    /** Successful sales per bucket and channel; buckets in time order. */
    private static function series(PDO $pdo, string $bucket, string $since, string $label): array
    {
        $rows = $pdo->query("SELECT $bucket AS b, MIN(s.created_at) AS first, c.type, COUNT(*) AS n
            FROM vend_sales s JOIN channels c ON c.id = s.channel_id
            WHERE s.state = 'SUCCEEDED' AND s.created_at >= $since GROUP BY b, c.type ORDER BY first")->fetchAll();
        $cols = [];
        $total = 0;
        foreach ($rows as $r) {
            $cols[$r['b']] ??= ['l' => $r['b'], 'web' => 0, 'app' => 0, 'pos' => 0, 'ussd' => 0];
            $cols[$r['b']][self::CHANNEL_KEYS[$r['type']]] += (int) $r['n'];
            $total += (int) $r['n'];
        }
        return ['note' => '<b>' . number_format($total) . ' tokens</b> sold, ' . $label . '.', 'cols' => array_values($cols)];
    }

    private static function terminals(PDO $pdo): array
    {
        $n = (int) $pdo->query('SELECT COUNT(DISTINCT terminal_id) FROM xmlvend_messages WHERE created_at >= NOW() - INTERVAL 1 HOUR')->fetchColumn();
        return ['active' => $n];
    }

    /** Each XMLVend terminal used in the last hour, with what it is doing now. */
    private static function workers(PDO $pdo): array
    {
        $rows = $pdo->query("SELECT m.terminal_id, m.operation, m.answered, m.recovered,
                TIMESTAMPDIFF(SECOND, m.created_at, NOW(6)) AS age,
                (SELECT COUNT(*) FROM xmlvend_messages x WHERE x.terminal_id = m.terminal_id AND x.created_at >= CURDATE() AND x.operation = 'creditvend') AS vends
            FROM xmlvend_messages m
            JOIN (SELECT terminal_id, MAX(id) id FROM xmlvend_messages WHERE operation <> 'advice' AND created_at >= NOW() - INTERVAL 1 HOUR GROUP BY terminal_id) last
              ON last.id = m.id ORDER BY m.terminal_id")->fetchAll();
        $out = [];
        foreach ($rows as $i => $r) {
            $open = $r['operation'] === 'creditvend' && (int) $r['answered'] === 0 && $r['recovered'] === null;
            // An open credit vend: in flight, then being advised; past the advice window its sale is
            // held for reconciliation and the terminal resolves it at its next sign-in.
            $state = !$open ? 'Idle' : ((int) $r['age'] <= 6 ? 'Sending' : ((int) $r['age'] <= 60 ? 'Recovering' : 'Held'));
            $out[] = ['id' => 'T' . ($i + 1), 'terminal' => $r['terminal_id'], 'q' => $open ? 1 : 0, 'state' => $state, 'vends' => (int) $r['vends']];
        }
        return $out;
    }

    private static function lastReconciliation(PDO $pdo): ?string
    {
        $t = $pdo->query("SELECT MAX(created_at) FROM audit_log WHERE action LIKE 'report.%' OR action LIKE '%reconcil%'")->fetchColumn();
        return $t ? substr((string) $t, 0, 16) : null;
    }

    private static function channelName(string $t): string
    {
        return ['WEB' => 'Web store', 'APP' => 'App', 'POS' => 'Merchant POS', 'USSD' => 'USSD'][$t] ?? $t;
    }

    private static function ledgerLabel(string $t): string
    {
        return ['deposit' => 'Deposit to BPC float', 'reserve' => 'Held for', 'settle' => 'Settled', 'release' => 'Released',
            'refund' => 'Refunded', 'fee' => 'Service fee'][$t] ?? $t;
    }

    private static function age(int $s): string
    {
        return $s < 90 ? "$s s" : ($s < 5400 ? round($s / 60) . ' min' : round($s / 3600, 1) . ' h');
    }
}
