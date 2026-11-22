<?php
declare(strict_types=1);

namespace MaruVend\Queue;

use MaruVend\Config;
use MaruVend\Settings;
use PDO;

/**
 * Only one site may vend at a time (clause 7.10, no double vending across sites).
 *
 * A worker may submit to BPC only if BOTH hold:
 *   1. the database it is connected to is writable (the demoted site's database is set
 *      read_only by the failover procedure and every database starts read-only, so its workers physically cannot record a
 *      submission, and a submission is always recorded before it is sent), and
 *   2. this server's site (MV_SITE) is the active_site recorded in that database.
 *
 * Promotion itself is decided by a three-voter quorum (both sites plus a witness), see
 * ops/scripts/mv-failover. Check 1 is the hard fence; check 2 stops a worker that was pointed at
 * the wrong database by mistake.
 */
final class SiteGuard
{
    public function __construct(private PDO $pdo, private Settings $settings) {}

    /** @return string|null null when vending is allowed, otherwise the reason it is not */
    public function blockedReason(): ?string
    {
        if ((int) $this->pdo->query('SELECT @@global.read_only')->fetchColumn() === 1) {
            return 'database is read-only (this site is not active)';
        }
        $site = Config::env('MV_SITE');
        if ($site !== null && $site !== $this->settings->get('active_site')) {
            return "this server is at site '$site' but the active site is '" . $this->settings->get('active_site') . "'";
        }
        return null;
    }
}
