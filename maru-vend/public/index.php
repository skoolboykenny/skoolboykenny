<?php
declare(strict_types=1);

// Optional local settings (cPanel hosting, see docs/cpanel.md). Never committed.
if (is_file(__DIR__ . '/../.env.php')) {
    require __DIR__ . '/../.env.php';
}
require __DIR__ . '/../vendor/autoload.php';

use MaruVend\Api\ApiApp;
use MaruVend\App;
use MaruVend\Dashboard\Dashboard;
use MaruVend\Portal\PortalWeb;

$factory = fn (?string $ip) => App::boot($ip);
$slim = ApiApp::create($factory);
Dashboard::register($slim, $factory);
PortalWeb::register($slim, $factory);
$slim->run();
