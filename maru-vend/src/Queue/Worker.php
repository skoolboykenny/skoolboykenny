<?php
declare(strict_types=1);

namespace MaruVend\Queue;

use MaruVend\Db;
use MaruVend\Settings;
use MaruVend\Vend\VendService;
use PDO;

/**
 * Queue worker (clause 7.6). Claims one ready job at a time with SELECT ... FOR UPDATE SKIP LOCKED,
 * so any number of workers on any number of servers share the queue without processing a sale twice.
 * Submissions to BPC are paced by the global RateLimiter inside VendService.
 */
final class Worker
{
    public function __construct(
        private PDO $pdo,
        private Settings $settings,
        private VendService $vend,
        private string $workerId,
    ) {}

    private ?SiteGuard $guard = null;
    private ?string $lastBlock = null;

    /** Claim and process one job. Returns false when nothing is ready (or this site may not vend). */
    public function runOnce(): bool
    {
        $this->guard ??= new SiteGuard($this->pdo, $this->settings);
        $blocked = $this->guard->blockedReason();
        if ($blocked !== null) {
            if ($blocked !== $this->lastBlock) {
                error_log("[worker {$this->workerId}] standing by: $blocked");
            }
            $this->lastBlock = $blocked;
            return false;
        }
        if ($this->lastBlock !== null) {
            error_log("[worker {$this->workerId}] site is active: resuming");
            $this->lastBlock = null;
        }
        $job = $this->claim();
        if (!$job) {
            return false;
        }
        try {
            $job['action'] === 'vend'
                ? $this->vend->processVend((int) $job['sale_id'])
                : $this->vend->processAdvice((int) $job['sale_id']);
        } catch (\Throwable $e) {
            // Leave the job for retry after the lock expires; the sale state machine makes this safe.
            error_log("[worker {$this->workerId}] job {$job['id']} sale {$job['sale_id']}: {$e->getMessage()}");
            $this->pdo->prepare('UPDATE queue_jobs SET locked_by = NULL, next_run_at = NOW(6) + INTERVAL 10 SECOND WHERE id = ?')->execute([$job['id']]);
        }
        return true;
    }

    public function run(?int $maxJobs = null, ?int $idleExitS = null): int
    {
        $done = 0;
        $idleSince = time();
        while ($maxJobs === null || $done < $maxJobs) {
            if ($this->runOnce()) {
                $done++;
                $idleSince = time();
            } else {
                if ($idleExitS !== null && time() - $idleSince >= $idleExitS) {
                    break;
                }
                usleep(200_000);
            }
        }
        return $done;
    }

    private function claim(): ?array
    {
        // A lock older than the worker timeout means its worker died; the job may be reclaimed.
        $stale = $this->settings->workerTimeout() + 30;
        return Db::tx($this->pdo, function (PDO $pdo) use ($stale) {
            $st = $pdo->prepare('SELECT id, sale_id, action FROM queue_jobs
                WHERE done = 0 AND next_run_at <= NOW(6)
                  AND (locked_by IS NULL OR locked_at < NOW(6) - INTERVAL ? SECOND)
                ORDER BY next_run_at, id LIMIT 1 FOR UPDATE SKIP LOCKED');
            $st->execute([$stale]);
            $job = $st->fetch();
            if ($job) {
                $pdo->prepare('UPDATE queue_jobs SET locked_by = ?, locked_at = NOW(6) WHERE id = ?')->execute([$this->workerId, $job['id']]);
            }
            return $job ?: null;
        });
    }
}
