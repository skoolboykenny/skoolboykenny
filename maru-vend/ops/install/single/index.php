<?php
// Maru Power front door. Everything else is packed in app.phar, next to this file.
if (is_file(__DIR__ . '/.env.php')) {
    require __DIR__ . '/.env.php';
}
require 'phar://' . __DIR__ . '/app.phar/public/index.php';
