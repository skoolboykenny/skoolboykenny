<?php
declare(strict_types=1);

namespace MaruVend;

use PDO;

final class Db
{
    public static function connect(?array $cfg = null): PDO
    {
        $cfg ??= Config::db();
        date_default_timezone_set('Africa/Gaborone'); // PHP and MariaDB must agree on local time
        $pdo = new PDO(
            sprintf('mysql:host=%s;port=%d;dbname=%s;charset=utf8mb4', $cfg['host'], $cfg['port'], $cfg['name']),
            $cfg['user'],
            $cfg['pass'],
            [
                PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
                PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
                PDO::ATTR_EMULATE_PREPARES => false,
            ]
        );
        $pdo->exec("SET time_zone = '+02:00'"); // Africa/Gaborone
        $pdo->exec('SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED');
        return $pdo;
    }

    /**
     * Run $fn inside a transaction, committing on success and rolling back on any error.
     * Deadlocks and lock wait timeouts are retried (up to 5 attempts); $fn must therefore only
     * touch the database, never an external system.
     */
    public static function tx(PDO $pdo, callable $fn): mixed
    {
        for ($attempt = 1; ; $attempt++) {
            $pdo->beginTransaction();
            try {
                $r = $fn($pdo);
                $pdo->commit();
                return $r;
            } catch (\Throwable $e) {
                if ($pdo->inTransaction()) {
                    $pdo->rollBack();
                }
                $retryable = $e instanceof \PDOException && in_array((int) ($e->errorInfo[1] ?? 0), [1213, 1205], true);
                if (!$retryable || $attempt >= 5) {
                    throw $e;
                }
                usleep(random_int(5_000, 50_000) * $attempt);
            }
        }
    }
}
