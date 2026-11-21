<?php
declare(strict_types=1);

namespace MaruVend\Queue;

use MaruVend\Db;
use MaruVend\Settings;
use PDO;

/**
 * Global limiter shared by every worker on every server: hands out submission slots spaced
 * 1/rate_per_s seconds apart, so BPC never receives more than rate_per_s requests per second
 * from Maru Vend however many channels are busy (clause 7.6).
 */
final class RateLimiter
{
    public function __construct(private PDO $pdo, private Settings $settings) {}

    public function acquire(): void
    {
        $rate = max(1, $this->settings->int('rate_per_s'));
        // The limiter row is created by migrate; locking it directly avoids the shared-to-exclusive
        // lock upgrade that INSERT IGNORE + SELECT FOR UPDATE would cause under concurrency.
        $slot = Db::tx($this->pdo, function (PDO $pdo) use ($rate) {
            $next = (float) $pdo->query('SELECT next_slot FROM rate_limiter WHERE id = 1 FOR UPDATE')->fetchColumn();
            $slot = max(microtime(true), $next);
            $pdo->prepare('UPDATE rate_limiter SET next_slot = ? WHERE id = 1')->execute([$slot + 1 / $rate]);
            return $slot;
        });
        $wait = $slot - microtime(true);
        if ($wait > 0) {
            usleep((int) ($wait * 1_000_000));
        }
    }
}
