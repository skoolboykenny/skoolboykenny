# Maru Power in five files (shared hosting)

For hosting where uploading hundreds of files is impractical. Upload into `public_html/maru-power/`:

| File | What it is |
|---|---|
| `app.phar` | the whole app, packed into one file (build below) |
| `index.php` | front door |
| `mv.php` | commands for cron and setup: `php mv.php worker --id=cron --idle-exit=55` |
| `.htaccess` | this folder's `htaccess`, renamed: sends everything through `index.php`, blocks the rest |
| `.env.php` | settings, made from `maru-vend/.env.php.example` |

Build `app.phar` (from `maru-vend`, after `composer install --no-dev`):

```bash
php -d phar.readonly=0 ops/install/single/mkphar.php "$PWD" app.phar
```
