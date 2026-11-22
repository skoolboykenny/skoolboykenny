<?php
declare(strict_types=1);

namespace MaruVend\Admin;

use MaruVend\Audit\AuditLog;
use MaruVend\Db;
use MaruVend\Settings;
use PDO;

/**
 * Two-person (maker-checker) control for sensitive changes: BPC endpoint, timeouts, limits,
 * provider, fee rate. One administrator requests, a different one approves; the change is
 * applied only from the approved payload, and both steps are in the audit trail.
 */
final class Approvals
{
    public function __construct(private PDO $pdo, private Settings $settings, private AuditLog $audit) {}

    public function requestSetting(string $name, string $value, string $maker): int
    {
        if (!array_key_exists($name, Settings::DEFAULTS)) {
            throw new \InvalidArgumentException("Unknown setting $name");
        }
        $payload = json_encode(['name' => $name, 'value' => $value]);
        $this->pdo->prepare("INSERT INTO approvals (action, payload, payload_hash, maker) VALUES ('setting.change', ?, ?, ?)")
            ->execute([$payload, hash('sha256', $payload), $maker]);
        $id = (int) $this->pdo->lastInsertId();
        $this->audit->record($maker, 'admin', 'approval.request', 'approvals', (string) $id, null, $payload);
        return $id;
    }

    public function approve(int $id, string $checker): void
    {
        Db::tx($this->pdo, function () use ($id, $checker) {
            $st = $this->pdo->prepare("SELECT * FROM approvals WHERE id = ? AND status = 'pending' FOR UPDATE");
            $st->execute([$id]);
            $a = $st->fetch();
            if (!$a) {
                throw new \RuntimeException("Approval $id is not pending");
            }
            if ($a['maker'] === $checker) {
                throw new \RuntimeException('The approver must be a different administrator from the requester');
            }
            if (!hash_equals($a['payload_hash'], hash('sha256', $a['payload']))) {
                throw new \RuntimeException('Approval payload was altered after it was requested');
            }
            $p = json_decode($a['payload'], true);
            $this->pdo->prepare("UPDATE approvals SET status = 'approved', checker = ?, decided_at = NOW(6) WHERE id = ?")->execute([$checker, $id]);
            $this->audit->record($checker, 'admin', 'approval.approve', 'approvals', (string) $id, null, $a['payload']);
            $this->settings->apply($p['name'], $p['value'], "{$a['maker']}+$checker", $this->audit);
        });
    }

    public function reject(int $id, string $checker): void
    {
        $this->pdo->prepare("UPDATE approvals SET status = 'rejected', checker = ?, decided_at = NOW(6) WHERE id = ? AND status = 'pending' AND maker <> ?")
            ->execute([$checker, $id, $checker]);
        $this->audit->record($checker, 'admin', 'approval.reject', 'approvals', (string) $id);
    }

    public function pending(): array
    {
        return $this->pdo->query("SELECT id, action, payload, maker, created_at FROM approvals WHERE status = 'pending' ORDER BY id")->fetchAll();
    }
}
