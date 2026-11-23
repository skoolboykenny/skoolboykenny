<?php
// Maru Vend commands, for cron jobs and setup, e.g.:  php mv.php worker --id=cron --idle-exit=55
if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}
if (is_file(__DIR__ . '/.env.php')) {
    require __DIR__ . '/.env.php';
}
require 'phar://' . __DIR__ . '/app.phar/bin/mv.php';
