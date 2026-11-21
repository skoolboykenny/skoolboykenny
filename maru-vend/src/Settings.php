<?php
declare(strict_types=1);

namespace MaruVend;

use MaruVend\Audit\AuditLog;
use PDO;

/**
 * Runtime settings held in the database, read on every use, so changes apply on the next
 * transaction with no code change or restart (clauses 7.8, 7.11).
 * Sensitive settings change only through two-person approval (see Approvals).
 */
final class Settings
{
    public const DEFAULTS = [
        'bpc_vat_no'         => 'P00000000000',
        'provider'           => 'simulator',
        'bpc_endpoint'       => 'http://127.0.0.1:8099',
        'bpc_endpoint_backup'=> '',
        'endpoint_active'    => 'primary',
        'bpc_timeout_s'      => '120',  // BPC's current configured timeout
        'worker_margin_s'    => '10',
        'channel_margin_s'   => '30',
        'rate_per_s'         => '5',    // max submissions per second to BPC, all workers combined
        'min_amount_thebe'   => '1000', // P10
        'max_amount_thebe'   => '500000',
        'float_alert_pct'    => '20',
        'max_unknown_thebe'  => '5000000', // cap on money held in unresolved sales
        'quote_ttl_s'        => '300',
        'advice_first_delay_s' => '125',
        'advice_interval_s'  => '80',
        'advice_window_s'    => '240',
        'unknown_alert_s'    => '7200',
        'service_fee_bp'     => '500',  // 5% of face value
        'receipt_prefix'     => 'MV',
        'active_site'        => 'primary',
    ];

    /** Settings that require maker-checker approval to change. */
    public const SENSITIVE = [
        'bpc_endpoint', 'bpc_endpoint_backup', 'endpoint_active', 'bpc_timeout_s', 'worker_margin_s',
        'channel_margin_s', 'rate_per_s', 'min_amount_thebe', 'max_amount_thebe', 'max_unknown_thebe',
        'service_fee_bp', 'provider', 'bpc_vat_no',
    ];

    public function __construct(private PDO $pdo) {}

    public function get(string $name): string
    {
        $st = $this->pdo->prepare('SELECT value FROM settings WHERE name = ?');
        $st->execute([$name]);
        $v = $st->fetchColumn();
        if ($v === false) {
            if (!array_key_exists($name, self::DEFAULTS)) {
                throw new \InvalidArgumentException("Unknown setting $name");
            }
            return self::DEFAULTS[$name];
        }
        return (string) $v;
    }

    public function int(string $name): int
    {
        return (int) $this->get($name);
    }

    /** Direct write: used by seeding and by Approvals once a change is approved. */
    public function apply(string $name, string $value, string $actor, AuditLog $audit): void
    {
        if (!array_key_exists($name, self::DEFAULTS)) {
            throw new \InvalidArgumentException("Unknown setting $name");
        }
        $this->validate($name, $value);
        $old = $this->get($name);
        $this->pdo->prepare('INSERT INTO settings (name, value) VALUES (?, ?) ON DUPLICATE KEY UPDATE value = VALUES(value)')
            ->execute([$name, $value]);
        $audit->record($actor, 'admin', 'setting.change', 'settings', $name, $old, $value);
    }

    private function validate(string $name, string $value): void
    {
        $numeric = ['bpc_timeout_s', 'worker_margin_s', 'channel_margin_s', 'rate_per_s', 'min_amount_thebe',
            'max_amount_thebe', 'float_alert_pct', 'max_unknown_thebe', 'quote_ttl_s', 'service_fee_bp'];
        if (in_array($name, $numeric, true) && (!ctype_digit($value) || (int) $value <= 0)) {
            throw new \InvalidArgumentException("$name must be a positive integer");
        }
        if ($name === 'endpoint_active' && !in_array($value, ['primary', 'backup'], true)) {
            throw new \InvalidArgumentException('endpoint_active must be primary or backup');
        }
    }

    // ---- derived timeouts (clause 7.8): change bpc_timeout_s and these follow ----

    public function workerTimeout(): int
    {
        return $this->int('bpc_timeout_s') + $this->int('worker_margin_s');
    }

    public function channelTimeout(): int
    {
        return $this->int('bpc_timeout_s') + $this->int('channel_margin_s');
    }

    /** Current BPC endpoint (FQDN or IP); switching applies on the next request (clause 7.11). */
    public function endpoint(): string
    {
        $useBackup = $this->get('endpoint_active') === 'backup' && $this->get('bpc_endpoint_backup') !== '';
        return $useBackup ? $this->get('bpc_endpoint_backup') : $this->get('bpc_endpoint');
    }
}
