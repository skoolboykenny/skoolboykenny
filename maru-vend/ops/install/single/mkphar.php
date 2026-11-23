<?php
// Pack Maru Vend into one file: app.phar (code, libraries, portal page, schema).
[$_, $src, $out] = $argv;
@unlink($out);
$p = new Phar($out);
$p->startBuffering();
$it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($src, FilesystemIterator::SKIP_DOTS));
foreach ($it as $f) {
    $rel = substr($f->getPathname(), strlen($src) + 1);
    if (preg_match('#^(src|channels/src|vendor|portal|database)/#', $rel) || $rel === 'public/index.php') {
        $p->addFile($f->getPathname(), $rel);
    }
}
// Command line entry without its shebang line, so it can be included.
$mv = file_get_contents("$src/bin/mv");
$p->addFromString('bin/mv.php', preg_replace('/^#!.*\n/', '', $mv));
$p->setStub("<?php __HALT_COMPILER();");
$p->stopBuffering();
echo count($p), " files packed\n";
