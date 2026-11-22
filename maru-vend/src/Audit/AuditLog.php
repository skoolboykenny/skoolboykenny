<?php
declare(strict_types=1);

namespace MaruVend\Audit;

use MaruVend\Config;
use PDO;

/**
 * Hash-chained audit trail (clause 7.4). Each row's hash covers its content and the previous
 * row's hash, so editing or deleting any row breaks the chain from that point on.
 *
 * Because a database administrator could rewrite the whole chain, the head is periodically
 * signed with a key the DB cannot read (anchor()), and the signed checkpoint is also written
 * outside the database. verify() checks both the chain and every anchor.
 */
final class AuditLog
{
    public const GENESIS = '0000000000000000000000000000000000000000000000000000000000000000';

    public function __construct(private PDO $pdo, private ?string $ip = null) {}

    public function record(string $actor, string $role, string $action, string $entity, ?string $entityId = null,
                           ?string $old = null, ?string $new = null): void
    {
        $write = function (PDO $pdo) use ($actor, $role, $action, $entity, $entityId, $old, $new): void {
            // Serialise writers on the single head row so two rows can never share a prev_hash.
            // (Locking "the latest audit_log row" is not enough: under concurrency a waiting writer
            // would still link to the row it originally read, not the one committed ahead of it.)
            $prev = $pdo->query('SELECT last_hash FROM audit_head WHERE id = 1 FOR UPDATE')->fetchColumn();
            if ($prev === false) {
                throw new \RuntimeException('audit_head row missing: run migrate');
            }
            $at = (new \DateTimeImmutable('now', new \DateTimeZone('Africa/Gaborone')))->format('Y-m-d H:i:s.u');
            $row = compact('actor', 'role', 'action', 'entity', 'old', 'new') + ['entity_id' => $entityId, 'ip' => $this->ip, 'at' => $at];
            $hash = self::hashRow($row, $prev);
            $pdo->prepare('INSERT INTO audit_log (actor, role, action, entity, entity_id, old_value, new_value, ip, created_at, prev_hash, hash)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?)')
                ->execute([$actor, $role, $action, $entity, $entityId, $old, $new, $this->ip, $at, $prev, $hash]);
            $pdo->prepare('UPDATE audit_head SET last_hash = ? WHERE id = 1')->execute([$hash]);
        };
        if ($this->pdo->inTransaction()) {
            $write($this->pdo);
        } else {
            \MaruVend\Db::tx($this->pdo, $write);
        }
    }

    public static function hashRow(array $r, string $prev): string
    {
        $canonical = json_encode([
            $r['actor'], $r['role'], $r['action'], $r['entity'], $r['entity_id'] ?? null,
            $r['old'] ?? null, $r['new'] ?? null, $r['ip'] ?? null, $r['at'], $prev,
        ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        return hash('sha256', $canonical);
    }

    /** Sign the current chain head with the anchor key and store it in the DB and outside it. */
    public function anchor(): ?array
    {
        $head = $this->pdo->query('SELECT id, hash FROM audit_log ORDER BY id DESC LIMIT 1')->fetch();
        if (!$head) {
            return null;
        }
        $count = (int) $this->pdo->query('SELECT COUNT(*) FROM audit_log')->fetchColumn();
        $sig = hash_hmac('sha256', "{$head['id']}|{$head['hash']}|$count", self::key());
        $this->pdo->prepare('INSERT INTO audit_anchors (last_id, head_hash, row_count, signature) VALUES (?,?,?,?)')
            ->execute([$head['id'], $head['hash'], $count, $sig]);
        $dir = Config::anchorDir();
        if (!is_dir($dir)) {
            mkdir($dir, 0700, true);
        }
        $line = json_encode(['last_id' => (int) $head['id'], 'head_hash' => $head['hash'], 'row_count' => $count,
            'signature' => $sig, 'at' => date('c')]) . "\n";
        file_put_contents($dir . '/anchors.jsonl', $line, FILE_APPEND | LOCK_EX);
        return ['last_id' => (int) $head['id'], 'head_hash' => $head['hash'], 'row_count' => $count];
    }

    /**
     * Verify the chain row by row, then check every anchor (from the external file, which a DB
     * administrator cannot alter) still matches the chain.
     * @return array{ok: bool, rows: int, problems: list<string>}
     */
    public function verify(): array
    {
        $problems = [];
        $prev = self::GENESIS;
        $rows = 0;
        $byId = [];
        $st = $this->pdo->query('SELECT * FROM audit_log ORDER BY id');
        while ($r = $st->fetch()) {
            $rows++;
            $calc = self::hashRow([
                'actor' => $r['actor'], 'role' => $r['role'], 'action' => $r['action'], 'entity' => $r['entity'],
                'entity_id' => $r['entity_id'], 'old' => $r['old_value'], 'new' => $r['new_value'], 'ip' => $r['ip'],
                'at' => self::fmt($r['created_at']),
            ], $prev);
            if ($r['prev_hash'] !== $prev) {
                $problems[] = "Row {$r['id']}: link to previous row broken (row deleted or inserted).";
            } elseif ($calc !== $r['hash']) {
                $problems[] = "Row {$r['id']}: content does not match its hash (row edited).";
            }
            $byId[(int) $r['id']] = $r['hash'];
            $prev = $r['hash'];
        }

        $file = Config::anchorDir() . '/anchors.jsonl';
        $anchors = is_file($file) ? array_filter(array_map(fn ($l) => json_decode($l, true), file($file))) : [];
        foreach ($anchors as $a) {
            $expect = hash_hmac('sha256', "{$a['last_id']}|{$a['head_hash']}|{$a['row_count']}", self::key());
            if (!hash_equals($expect, $a['signature'])) {
                $problems[] = "Anchor at row {$a['last_id']}: signature invalid.";
            } elseif (($byId[$a['last_id']] ?? null) !== $a['head_hash']) {
                $problems[] = "Anchor at row {$a['last_id']}: chain no longer matches the signed checkpoint (chain rewritten).";
            }
        }
        return ['ok' => $problems === [], 'rows' => $rows, 'anchors' => count($anchors), 'problems' => $problems];
    }

    private static function fmt(string $dt): string
    {
        // MariaDB returns DATETIME(6) with microseconds; normalise to 6 digits.
        return str_contains($dt, '.') ? str_pad($dt, 26, '0') : $dt . '.000000';
    }

    private static function key(): string
    {
        $f = Config::anchorKeyFile();
        if (!is_file($f)) {
            file_put_contents($f, bin2hex(random_bytes(32)));
            chmod($f, 0600);
        }
        return trim((string) file_get_contents($f));
    }
}
