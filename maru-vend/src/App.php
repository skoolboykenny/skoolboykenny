<?php
declare(strict_types=1);

namespace MaruVend;

use MaruVend\Admin\Approvals;
use MaruVend\Audit\AuditLog;
use MaruVend\Float\FloatLedger;
use MaruVend\Provider\ProviderFactory;
use MaruVend\Provider\VendProvider;
use MaruVend\Queue\RateLimiter;
use MaruVend\Queue\Worker;
use MaruVend\Reports\Reports;
use MaruVend\Vend\VendService;
use PDO;

/** Small service container wiring the platform together. */
final class App
{
    public readonly Settings $settings;
    public readonly AuditLog $audit;

    private string $process = 'api';

    public function __construct(public readonly PDO $pdo, ?string $ip = null, private ?VendProvider $provider = null)
    {
        $this->settings = new Settings($pdo);
        $this->audit = new AuditLog($pdo, $ip);
    }

    public static function boot(?string $ip = null): self
    {
        return new self(Db::connect(), $ip);
    }

    public function provider(): VendProvider
    {
        return $this->provider ??= ProviderFactory::make($this->settings, $this->pdo, $this->process);
    }

    public function vend(): VendService
    {
        return new VendService($this->pdo, $this->settings, $this->provider(), $this->audit, new RateLimiter($this->pdo, $this->settings));
    }

    public function worker(string $id): Worker
    {
        if ($this->provider === null) {
            $this->process = $id; // own XMLVend terminal per worker
        }
        return new Worker($this->pdo, $this->settings, $this->vend(), $id);
    }

    public function float(): FloatLedger
    {
        return new FloatLedger($this->pdo);
    }

    public function reports(): Reports
    {
        return new Reports($this->pdo, $this->settings);
    }

    public function approvals(): Approvals
    {
        return new Approvals($this->pdo, $this->settings, $this->audit);
    }

    public static function migrate(PDO $pdo): void
    {
        $sql = file_get_contents(__DIR__ . '/../database/schema.sql');
        foreach (array_filter(array_map('trim', preg_split('/;\s*$/m', $sql))) as $stmt) {
            if (!preg_match('/^(--[^\n]*\n\s*)*$/', $stmt)) {
                $pdo->exec($stmt);
            }
        }
        $pdo->exec('INSERT IGNORE INTO float_position (id, available, reserved, last_deposit_thebe) VALUES (1, 0, 0, 0)');
        $pdo->exec('INSERT IGNORE INTO rate_limiter (id, next_slot) VALUES (1, 0)');
        $pdo->exec("INSERT IGNORE INTO audit_head (id, last_hash)
            SELECT 1, COALESCE((SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1), '" . AuditLog::GENESIS . "')");
    }
}
