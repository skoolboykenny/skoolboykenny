<?php
declare(strict_types=1);

namespace MaruVend\Tests;

use MaruVend\App;
use MaruVend\Db;
use MaruVend\Vend\VendService;
use PDO;

abstract class TestCase extends \PHPUnit\Framework\TestCase
{
    protected PDO $pdo;
    protected App $app;
    protected FakeProvider $provider;
    protected VendService $vend;
    protected array $pos;
    protected array $web;

    protected function setUp(): void
    {
        putenv('MV_ANCHOR_DIR=' . sys_get_temp_dir() . '/mv-test-anchors-' . getmypid());
        putenv('MV_ANCHOR_KEY_FILE=' . sys_get_temp_dir() . '/mv-test-anchor-' . getmypid() . '.key');
        @unlink(sys_get_temp_dir() . '/mv-test-anchors-' . getmypid() . '/anchors.jsonl');

        $cfg = ['host' => '127.0.0.1', 'port' => 3306, 'name' => getenv('MV_TEST_DB') ?: 'maruvend_test',
            'user' => 'maruvend', 'pass' => getenv('MV_DB_PASS') ?: 'devpass'];
        $this->pdo = Db::connect($cfg);
        $this->pdo->exec('SET FOREIGN_KEY_CHECKS = 0');
        foreach ($this->pdo->query('SHOW FULL TABLES WHERE Table_type = "BASE TABLE"')->fetchAll(PDO::FETCH_NUM) as [$t]) {
            $this->pdo->exec("DROP TABLE `$t`");
        }
        $this->pdo->exec('SET FOREIGN_KEY_CHECKS = 1');
        App::migrate($this->pdo);

        $this->pdo->exec("INSERT INTO merchants (id, code, name, kyc_status) VALUES (1,'M1','Test Merchant','verified')");
        $this->pdo->exec("INSERT INTO channels (id, merchant_id, type, is_24h, api_key, api_secret) VALUES
            (1,1,'POS',0,'pos','pos-secret'),(2,1,'WEB',1,'web','web-secret')");
        $this->pos = $this->pdo->query('SELECT * FROM channels WHERE id = 1')->fetch();
        $this->web = $this->pdo->query('SELECT * FROM channels WHERE id = 2')->fetch();

        $this->provider = new FakeProvider();
        $this->app = new App($this->pdo, '127.0.0.1', $this->provider);
        $this->vend = new VendService($this->pdo, $this->app->settings, $this->provider, $this->app->audit);
        Db::tx($this->pdo, fn () => $this->app->float()->deposit(1_000_000, 'DEP1', 'test'));
    }

    /** Create a POS sale and run it through the queue. */
    protected function posSale(int $amount = 2500, string $meter = '94949494949'): array
    {
        $s = $this->vend->quote($this->pos, $meter, $amount, 'k' . bin2hex(random_bytes(6)));
        $this->vend->accept($this->pos, (int) $s['id']);
        return $this->vend->sale((int) $s['id']);
    }

    protected function float(): array
    {
        return $this->app->float()->position();
    }

    protected function states(int $saleId): array
    {
        $st = $this->pdo->prepare('SELECT to_state FROM sale_events WHERE sale_id = ? ORDER BY seq');
        $st->execute([$saleId]);
        return $st->fetchAll(PDO::FETCH_COLUMN);
    }
}
