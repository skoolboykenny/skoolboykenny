<?php
declare(strict_types=1);

namespace MaruVend\Portal;

use MaruVend\App;
use PDO;

/**
 * Where Maru Power customer accounts live.
 *
 * Production: the Maru Quick website database (maruquic_marugroupdata), in its own tables
 * power_users and power_codes, separate from the Supply Portal's supply_users. Configure with
 *   MV_ACCOUNTS_DB_HOST, MV_ACCOUNTS_DB_PORT, MV_ACCOUNTS_DB_NAME, MV_ACCOUNTS_DB_USER, MV_ACCOUNTS_DB_PASS
 * and create the tables with website/sql/maru_power_accounts.sql.
 *
 * Not configured (demo, tests): the accounts stay in the Maru Vend database (portal_users, portal_codes).
 *
 * Meters linked to an account, and every sale, stay in Maru Vend; they refer to the account by its id.
 */
final class Accounts
{
    public function __construct(public readonly PDO $pdo, public readonly string $users, public readonly string $codes) {}

    public static function for(App $app): self
    {
        $name = getenv('MV_ACCOUNTS_DB_NAME');
        if ($name === false || $name === '') {
            return new self($app->pdo, 'portal_users', 'portal_codes');
        }
        static $pdo = null;
        $pdo ??= self::connect([
            'host' => getenv('MV_ACCOUNTS_DB_HOST') ?: '127.0.0.1',
            'port' => (int) (getenv('MV_ACCOUNTS_DB_PORT') ?: 3306),
            'name' => $name,
            'user' => (string) getenv('MV_ACCOUNTS_DB_USER'),
            'pass' => (string) getenv('MV_ACCOUNTS_DB_PASS'),
        ]);
        $prefix = getenv('MV_ACCOUNTS_PREFIX') ?: 'power_';
        return new self($pdo, $prefix . 'users', $prefix . 'codes');
    }

    public static function connect(array $c): PDO
    {
        $pdo = new PDO(sprintf('mysql:host=%s;port=%d;dbname=%s;charset=utf8mb4', $c['host'], $c['port'], $c['name']), $c['user'], $c['pass'], [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES => false,
        ]);
        $pdo->exec("SET time_zone = '+02:00'");
        return $pdo;
    }

    public function one(string $sql, array $p = []): ?array
    {
        $st = $this->pdo->prepare($this->t($sql));
        $st->execute($p);
        return $st->fetch() ?: null;
    }

    public function all(string $sql, array $p = []): array
    {
        $st = $this->pdo->prepare($this->t($sql));
        $st->execute($p);
        return $st->fetchAll();
    }

    public function run(string $sql, array $p = []): int
    {
        $st = $this->pdo->prepare($this->t($sql));
        $st->execute($p);
        return $st->rowCount();
    }

    public function lastId(): int
    {
        return (int) $this->pdo->lastInsertId();
    }

    /** {users} and {codes} in SQL become the configured table names. */
    private function t(string $sql): string
    {
        return str_replace(['{users}', '{codes}'], [$this->users, $this->codes], $sql);
    }
}
