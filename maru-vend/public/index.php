<?php
declare(strict_types=1);

require __DIR__ . '/../vendor/autoload.php';

use MaruVend\Api\ApiApp;
use MaruVend\App;
use MaruVend\Dashboard\Dashboard;

$factory = fn (?string $ip) => App::boot($ip);
$slim = ApiApp::create($factory);
Dashboard::register($slim, $factory);
$slim->run();
