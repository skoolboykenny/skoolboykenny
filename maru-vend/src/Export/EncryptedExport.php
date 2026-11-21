<?php
declare(strict_types=1);

namespace MaruVend\Export;

use MaruVend\Audit\AuditLog;
use MaruVend\Config;

/**
 * Exports are encrypted to BPC's OpenPGP public key (AES-256) so only BPC can open them,
 * and signed with Maru Quick's key so BPC can verify origin and integrity (clause 7.5).
 * The fingerprint of BPC's key is pinned in configuration after out-of-band confirmation.
 * Every export is recorded in the audit trail. Server copies are purged after 30 days.
 */
final class EncryptedExport
{
    public function __construct(private AuditLog $audit, private string $gpgHome, private string $recipientFpr, private ?string $signerFpr = null) {}

    public static function fromEnv(AuditLog $audit): self
    {
        return new self(
            $audit,
            (string) Config::env('MV_GPG_HOME', getenv('HOME') . '/.gnupg'),
            (string) Config::env('MV_BPC_KEY_FPR', ''),
            Config::env('MV_SIGNER_KEY_FPR'),
        );
    }

    /** Encrypt $content and write it to $outFile (.gpg). Returns the output path. */
    public function export(string $name, string $content, string $outFile, string $actor): string
    {
        if ($this->recipientFpr === '') {
            throw new \RuntimeException('BPC export key fingerprint (MV_BPC_KEY_FPR) is not configured');
        }
        $plain = tempnam(sys_get_temp_dir(), 'mvx');
        file_put_contents($plain, $content);
        $args = ['gpg', '--homedir', $this->gpgHome, '--batch', '--yes', '--trust-model', 'always',
            '--cipher-algo', 'AES256', '--recipient', $this->recipientFpr, '--output', $outFile];
        if ($this->signerFpr) {
            array_push($args, '--local-user', $this->signerFpr, '--sign');
        }
        array_push($args, '--encrypt', $plain);
        $proc = proc_open($args, [1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $pipes);
        $err = stream_get_contents($pipes[2]);
        $code = proc_close($proc);
        // Overwrite then remove the plaintext immediately.
        file_put_contents($plain, str_repeat("\0", strlen($content)));
        unlink($plain);
        if ($code !== 0) {
            throw new \RuntimeException('Encryption failed: ' . trim($err));
        }
        $this->audit->record($actor, 'admin', 'export.create', 'export', $name, null,
            json_encode(['file' => basename($outFile), 'sha256' => hash_file('sha256', $outFile), 'recipient' => $this->recipientFpr]));
        return $outFile;
    }

    /** Delete encrypted exports older than $days from $dir. */
    public static function purge(string $dir, int $days = 30): int
    {
        $n = 0;
        foreach (glob(rtrim($dir, '/') . '/*.gpg') ?: [] as $f) {
            if (filemtime($f) < time() - $days * 86400) {
                unlink($f);
                $n++;
            }
        }
        return $n;
    }
}
