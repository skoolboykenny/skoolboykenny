<?php
declare(strict_types=1);

namespace MaruVend\Sms;

use MaruVend\Config;
use MaruVend\Db;
use PDO;

/**
 * Sends queued customer SMS (tokens and failure notices) through the configured provider.
 *
 * MV_SMS_PROVIDER=log   test environment: messages are marked sent and written to MV_SMS_LOG
 * MV_SMS_PROVIDER=http  generic bulk-SMS HTTP API (MV_SMS_URL, MV_SMS_TOKEN, MV_SMS_SENDER);
 *                       adapt send() to the contracted Botswana provider's request format.
 * A second provider can be configured as MV_SMS_FALLBACK_URL for failover.
 */
final class SmsSender
{
    public function __construct(private PDO $pdo) {}

    /** Send up to $limit queued messages. Returns the number sent. */
    public function run(int $limit = 50): int
    {
        $rows = Db::tx($this->pdo, function (PDO $pdo) use ($limit) {
            $rows = $pdo->query("SELECT * FROM sms_outbox WHERE status = 'queued' AND attempts < 5 ORDER BY id LIMIT $limit FOR UPDATE SKIP LOCKED")->fetchAll();
            foreach ($rows as $r) {
                $pdo->prepare('UPDATE sms_outbox SET attempts = attempts + 1 WHERE id = ?')->execute([$r['id']]);
            }
            return $rows;
        });
        $sent = 0;
        foreach ($rows as $r) {
            $ref = $this->send('267' . $r['msisdn'], $r['body']);
            if ($ref !== null) {
                $this->pdo->prepare("UPDATE sms_outbox SET status = 'sent', provider_ref = ?, sent_at = NOW(6) WHERE id = ?")->execute([$ref, $r['id']]);
                $sent++;
            } elseif ((int) $r['attempts'] + 1 >= 5) {
                $this->pdo->prepare("UPDATE sms_outbox SET status = 'failed' WHERE id = ?")->execute([$r['id']]);
            }
        }
        return $sent;
    }

    private function send(string $to, string $body): ?string
    {
        if (Config::env('MV_SMS_PROVIDER', 'log') === 'log') {
            $line = sprintf("[%s] to +%s: %s\n", date('Y-m-d H:i:s'), $to, $body);
            file_put_contents((string) Config::env('MV_SMS_LOG', sys_get_temp_dir() . '/maruvend-sms.log'), $line, FILE_APPEND | LOCK_EX);
            return 'LOG-' . substr(hash('sha256', $line), 0, 12);
        }
        foreach (array_filter([Config::env('MV_SMS_URL'), Config::env('MV_SMS_FALLBACK_URL')]) as $url) {
            $ch = curl_init($url);
            curl_setopt_array($ch, [CURLOPT_POST => true, CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 15,
                CURLOPT_HTTPHEADER => ['Content-Type: application/json', 'Authorization: Bearer ' . Config::env('MV_SMS_TOKEN', '')],
                CURLOPT_POSTFIELDS => json_encode(['from' => Config::env('MV_SMS_SENDER', 'MaruQuick'), 'to' => $to, 'text' => $body])]);
            $resp = curl_exec($ch);
            $code = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
            if ($resp !== false && $code >= 200 && $code < 300) {
                return (string) (json_decode((string) $resp, true)['id'] ?? 'OK');
            }
        }
        return null;
    }
}
