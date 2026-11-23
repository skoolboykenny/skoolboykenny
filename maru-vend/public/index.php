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
// When installed in a folder of the website (e.g. public_html/maru-power), MV_BASE_PATH=/maru-power.
$slim->setBasePath(rtrim((string) getenv('MV_BASE_PATH'), '/'));
Dashboard::register($slim, $factory);
PortalWeb::register($slim, $factory);
// Unknown addresses get a plain "Not found"; errors never show code or file paths to visitors.
$errors = $slim->addErrorMiddleware(false, true, false);
$errors->setDefaultErrorHandler(function (\Psr\Http\Message\ServerRequestInterface $req, \Throwable $e) use ($slim) {
    $notFound = $e instanceof \Slim\Exception\HttpNotFoundException || $e instanceof \Slim\Exception\HttpMethodNotAllowedException;
    if (!$notFound) {
        error_log('[maru-vend] ' . $e);
    }
    $res = $slim->getResponseFactory()->createResponse($notFound ? 404 : 500);
    $res->getBody()->write($notFound ? 'Not found' : 'Something went wrong. Please try again.');
    return $res->withHeader('Content-Type', 'text/plain; charset=utf-8');
});
$slim->run();
