<?php
declare(strict_types=1);

namespace MaruVend\Tests;

/** Many processes writing audit entries at once must still produce one unbroken chain. */
final class AuditConcurrencyTest extends TestCase
{
    public function testConcurrentWritersKeepChainIntact(): void
    {
        $script = sys_get_temp_dir() . '/mv-audit-writer.php';
        file_put_contents($script, '<?php require "' . dirname(__DIR__) . '/vendor/autoload.php";
            $pdo = MaruVend\Db::connect(["host"=>"127.0.0.1","port"=>3306,"name"=>"' . (getenv('MV_TEST_DB') ?: 'maruvend_test') . '","user"=>"maruvend","pass"=>"' . (getenv('MV_DB_PASS') ?: 'devpass') . '"]);
            $a = new MaruVend\Audit\AuditLog($pdo);
            for ($i = 0; $i < 40; $i++) { $a->record("w".$argv[1], "test", "concurrency", "x", (string) $i); }');
        $procs = [];
        for ($w = 0; $w < 8; $w++) {
            $procs[] = proc_open([PHP_BINARY, $script, (string) $w], [], $pipes);
        }
        foreach ($procs as $p) {
            $this->assertSame(0, proc_close($p));
        }
        $r = $this->app->audit->verify();
        $this->assertTrue($r['ok'], implode("\n", $r['problems']));
        $this->assertGreaterThanOrEqual(320, $r['rows']);
    }
}
