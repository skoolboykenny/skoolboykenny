# Running Maru Power on cPanel hosting (no VPS)

Maru Vend, the system behind the Maru Power portal, is plain PHP, so it can run on the same cPanel
hosting as maruquick.com. The one difference from a server: the queue worker that issues tokens
runs as a **cron job every minute** instead of running all the time, so a purchase can take up to
about a minute to complete.

## What the hosting must have

Check these in cPanel before starting:

| Need | Where to check |
|---|---|
| PHP **8.3 or newer**, with `pdo_mysql`, `curl`, `mbstring` | *Select PHP Version* / *MultiPHP Manager* |
| **MariaDB 10.6 or newer** (not MySQL) | phpMyAdmin home page, "Server type" |
| **Cron jobs** | *Cron Jobs* |
| **Subdomains** | *Domains* / *Subdomains* |
| Terminal or SSH (helpful, not required) | *Terminal* |

## 1. Upload the code

1. On your PC, in `maru-vend`, run `composer install --no-dev` so the `vendor` folder exists.
2. Zip the whole `maru-vend` folder and upload it with *File Manager* to your home folder,
   **outside** `public_html`, e.g. `/home/maruquic/maru-vend`. Extract it there.

Only `maru-vend/public` will be reachable from the web; code and settings stay private.

## 2. Create the subdomain

*Domains* → create `power.maruquick.com` with **document root** `maru-vend/public`.
Turn on HTTPS for it (*SSL/TLS Status* → *Run AutoSSL*).

## 3. Create the Maru Vend database

*MySQL Databases*:
1. Create database `maruquic_maruvend`.
2. Create user `maruquic_mvend` with a strong password, add it to that database with **All privileges**.
3. Create user `maruquic_mpower` with a different strong password, and give it **only** SELECT, INSERT,
   UPDATE on `maruquic_marugroupdata`. (In phpMyAdmin you can narrow this further to the
   `power_users` and `power_codes` tables; see `website/sql/maru_power_accounts.sql`.)

## 4. Settings

Create `maru-vend/.env.php` (it is outside `public`, so it cannot be downloaded):

```php
<?php
// Maru Vend settings for cPanel. Never commit this file.
foreach ([
    'MV_DB_HOST' => 'localhost',
    'MV_DB_NAME' => 'maruquic_maruvend',
    'MV_DB_USER' => 'maruquic_mvend',
    'MV_DB_PASS' => '...',
    // Maru Power accounts live in the website database.
    'MV_ACCOUNTS_DB_HOST' => 'localhost',
    'MV_ACCOUNTS_DB_NAME' => 'maruquic_marugroupdata',
    'MV_ACCOUNTS_DB_USER' => 'maruquic_mpower',
    'MV_ACCOUNTS_DB_PASS' => '...',
    // Same value as MQ_POWER_SSO_SECRET in the website's includes/mq_secrets.php. 32+ random characters.
    'MV_SSO_SECRET' => '...',
    'MV_SECURE_COOKIES' => '1',
    // Test mode until payment providers and a token source are contracted.
    'MV_PAYMENTS' => 'test',
] as $k => $v) {
    putenv("$k=$v");
}
```

## 5. Create the tables and demo data

With *Terminal* (or SSH), from `maru-vend`:

```bash
php bin/mv migrate
```

```bash
php bin/mv seed
```

Without a terminal, add both as one-off cron jobs (see step 6 for the format), let them run once,
then delete them.

## 6. Cron jobs

*Cron Jobs* → add each with **every minute** (`* * * * *`). Replace the path with yours.

Queue worker (issues tokens; runs about 55 seconds, then the next one starts):

```bash
cd /home/maruquic/maru-vend && /usr/local/bin/php bin/mv worker --id=cron --idle-exit=55 >/dev/null 2>&1
```

SMS sender:

```bash
cd /home/maruquic/maru-vend && /usr/local/bin/php bin/mv sms --once >/dev/null 2>&1
```

Expire old quotes (every 10 minutes is enough, `*/10 * * * *`):

```bash
cd /home/maruquic/maru-vend && /usr/local/bin/php bin/mv sweep >/dev/null 2>&1
```

The PHP path differs between hosts: cPanel shows the right one on the *Cron Jobs* page, or use
`/opt/cpanel/ea-php83/root/usr/bin/php`.

## 7. Connect the website

In the website's `includes/mq_secrets.php`:

```php
define('MQ_POWER_URL', 'https://power.maruquick.com/power');
define('MQ_POWER_SSO_SECRET', '...');   // same as MV_SSO_SECRET
```

Now signing up or logging in on maruquick.com opens the Maru Power portal.

## 8. Check it

- `https://power.maruquick.com/health` shows `{"ok":true}`.
- Log in on `maruquick.com/maru_power_login.php`: you land in the portal.
- `https://power.maruquick.com/bpc` is the operator dashboard (create a user with
  `php bin/mv user:add <name> admin`).

## Limits of shared hosting

- Tokens take up to a minute, not seconds.
- No second site for failover; fine for a pilot, not for full production.
- Real tokens still need a token source (BPC directly or a licensed vendor), and real payments need
  merchant accounts. Until then the platform runs in test mode.
