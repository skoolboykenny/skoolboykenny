<?php
/*
 * Shared code for the Maru Power pages on the Maru Quick website
 * (maru_power_signup.php, maru_power_login.php, maru_power_account.php).
 *
 * Accounts are stored in the Maru Quick database (power_users, created by sql/maru_power_accounts.sql),
 * separate from the Supply Portal's supply_users.
 *
 * Settings, in includes/mq_secrets.php:
 *   MQ_DB_USER, MQ_DB_PASS            already there
 *   MQ_POWER_URL                      public address of the Maru Power portal, e.g. https://power.maruquick.com/power
 *   MQ_POWER_SSO_SECRET               32+ characters, same value as MV_SSO_SECRET on the Maru Power server
 * Until MQ_POWER_URL and MQ_POWER_SSO_SECRET are set, people can still create accounts and log in;
 * they then see their account page here instead of being sent to the portal.
 */
require_once __DIR__ . '/includes/mq_secrets.php';

function mp_session(): void
{
    if (session_status() !== PHP_SESSION_ACTIVE) {
        $secure = !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off';
        session_name('mq_power');
        session_start(['cookie_httponly' => true, 'cookie_samesite' => 'Lax', 'cookie_secure' => $secure]);
    }
    if (empty($_SESSION['mp_csrf'])) {
        $_SESSION['mp_csrf'] = bin2hex(random_bytes(16));
    }
}

function mp_e($s): string
{
    return htmlspecialchars((string) $s, ENT_QUOTES, 'UTF-8');
}

function mp_db(): PDO
{
    static $pdo = null;
    if ($pdo === null) {
        $pdo = new PDO('mysql:host=localhost;port=3306;dbname=maruquic_marugroupdata;charset=utf8mb4', MQ_DB_USER, MQ_DB_PASS, [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION, PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC, PDO::ATTR_EMULATE_PREPARES => false,
        ]);
        $pdo->exec("SET time_zone = '+02:00'");
    }
    return $pdo;
}

function mp_csrf_ok(): bool
{
    return hash_equals($_SESSION['mp_csrf'] ?? '', (string) ($_POST['csrf'] ?? ''));
}

/** The portal address, only when the portal is really set up (never a local test address). */
function mp_portal_url(): ?string
{
    $url = defined('MQ_POWER_URL') ? (string) MQ_POWER_URL : '';
    $secret = defined('MQ_POWER_SSO_SECRET') ? (string) MQ_POWER_SSO_SECRET : '';
    return ($url !== '' && strlen($secret) >= 32) ? rtrim($url, '/') : null;
}

/** Sign-in ticket for the portal. Format must match maru-vend/src/Portal/Sso.php. */
function mp_ticket(int $uid): string
{
    $body = rtrim(strtr(base64_encode(json_encode(['uid' => $uid, 'exp' => time() + 60, 'n' => bin2hex(random_bytes(16))])), '+/', '-_'), '=');
    return $body . '.' . hash_hmac('sha256', $body, (string) MQ_POWER_SSO_SECRET);
}

/** After sign-up or log-in: open the portal if it is online, otherwise the account page here. */
function mp_signed_in(int $uid): void
{
    session_regenerate_id(true);
    $_SESSION['mp_uid'] = $uid;
    $portal = mp_portal_url();
    header('Referrer-Policy: no-referrer');
    header('Location: ' . ($portal ? $portal . '/sso?t=' . rawurlencode(mp_ticket($uid)) : 'maru_power_account.php'), true, 303);
    exit();
}

/** Same rules as Maru Power's own sign-up (maru-vend/src/Portal/Portal.php). Returns the new id. */
function mp_create_account(array $in): int
{
    $type = ($in['account_type'] ?? '') === 'business' ? 'business' : 'household';
    $name = trim((string) ($in['name'] ?? ''));
    $email = strtolower(trim((string) ($in['email'] ?? '')));
    $pw = (string) ($in['password'] ?? '');
    $company = mb_substr(trim((string) ($in['company_name'] ?? '')), 0, 160);
    $reg = strtoupper(preg_replace('/\s+/', '', (string) ($in['company_reg'] ?? '')));
    $vat = strtoupper(preg_replace('/\s+/', '', (string) ($in['vat_no'] ?? '')));

    if ($name === '' || !filter_var($email, FILTER_VALIDATE_EMAIL)) {
        throw new InvalidArgumentException('Enter your name and a valid email address.');
    }
    if (strlen($pw) < 8) {
        throw new InvalidArgumentException('Password must be at least 8 characters.');
    }
    if ($pw !== (string) ($in['password2'] ?? '')) {
        throw new InvalidArgumentException('The two passwords do not match.');
    }
    if ($type === 'business') {
        if ($company === '') {
            throw new InvalidArgumentException('Enter the registered company name.');
        }
        if (!preg_match('/^[A-Z0-9\/-]{4,40}$/', $reg)) {
            throw new InvalidArgumentException('Enter the company registration number (CIPA UIN).');
        }
        if ($vat !== '' && !preg_match('/^[A-Z0-9\/-]{4,40}$/', $vat)) {
            throw new InvalidArgumentException('That VAT number does not look right.');
        }
    }
    $db = mp_db();
    $st = $db->prepare('SELECT id FROM power_users WHERE email = ?');
    $st->execute([$email]);
    if ($st->fetch()) {
        throw new InvalidArgumentException('An account with this email already exists. Please log in.');
    }
    $db->prepare('INSERT INTO power_users (name, account_type, company_name, company_reg, vat_no, email, password_hash) VALUES (?,?,?,?,?,?,?)')
        ->execute([$name, $type, $type === 'business' ? $company : null, $type === 'business' ? $reg : null,
            $type === 'business' && $vat !== '' ? $vat : null, $email, password_hash($pw, PASSWORD_DEFAULT)]);
    return (int) $db->lastInsertId();
}

function mp_head(string $title): void
{
    header('X-Frame-Options: DENY');
    ?><!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Maru Quick — <?= mp_e($title) ?></title>
<link rel="icon" type="image/png" href="favicon.png">
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@600;700;800;900&family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&display=swap" rel="stylesheet">
<style>
*, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }
a { text-decoration:none; color:inherit; }
:root { --yellow:#F5C518; --yellow-dk:#D4A900; --yellow-pale:#FFFBEA; --dark:#0E0E0E; --mid:#6B7280; --light:#F8F7F4; --white:#FFFFFF; --blue:#1A6BFF; --border:#E5E7EB; --red:#B42318; --red-pale:#FDECEC; --green:#157A3C; --green-pale:#E8F5EC; --fh:'Sora', sans-serif; --fb:'DM Sans', sans-serif; --px:clamp(20px, 5vw, 72px); }
body { font-family:var(--fb); background:var(--yellow); color:var(--dark); line-height:1.6; min-height:100vh; display:flex; flex-direction:column; }
header { background:var(--white); border-bottom:1px solid var(--border); }
.header-inner { max-width:1280px; margin:0 auto; padding:0 var(--px); height:70px; display:flex; align-items:center; justify-content:space-between; }
.logo img { height:44px; width:auto; }
.logo-fallback { font-family:var(--fh); font-size:1.3rem; font-weight:800; }
.logo-fallback span { color:var(--yellow-dk); }
.back { font-size:.88rem; font-weight:600; color:var(--mid); }
main { flex:1; display:grid; place-items:center; padding:48px 20px; position:relative; overflow:hidden; }
main::before { content:''; position:absolute; top:-120px; right:-120px; width:480px; height:480px; border-radius:50%; background:rgba(255,255,255,.14); }
.card { position:relative; width:100%; max-width:480px; background:var(--white); border-radius:24px; padding:36px 32px; box-shadow:0 24px 60px rgba(0,0,0,.12); }
.tag { display:inline-flex; align-items:center; gap:7px; background:var(--yellow-pale); color:var(--yellow-dk); padding:5px 12px; border-radius:50px; font-size:.75rem; font-weight:700; letter-spacing:.05em; text-transform:uppercase; margin-bottom:16px; }
.tag svg { width:13px; height:13px; }
h1 { font-family:var(--fh); font-size:1.7rem; font-weight:800; letter-spacing:-.02em; margin-bottom:6px; line-height:1.2; }
.sub { color:var(--mid); font-size:.92rem; margin-bottom:22px; }
label { display:block; font-weight:600; font-size:.85rem; margin:14px 0 6px; }
label small { font-weight:400; color:var(--mid); }
input { width:100%; font:inherit; font-size:1rem; padding:13px 14px; border:1.5px solid var(--border); border-radius:12px; background:var(--white); }
input:focus { outline:none; border-color:var(--yellow); box-shadow:0 0 0 3px rgba(245,197,24,.25); }
.types { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.types label { margin:0; border:1.5px solid var(--border); border-radius:14px; padding:14px; cursor:pointer; font-weight:500; }
.types input { position:absolute; opacity:0; width:1px; height:1px; }
.types b { display:block; font-family:var(--fh); font-size:.95rem; }
.types span { font-size:.78rem; color:var(--mid); }
.types label:has(input:checked) { border-color:var(--dark); background:var(--yellow-pale); }
.types label:has(input:focus-visible) { box-shadow:0 0 0 3px rgba(245,197,24,.45); }
.err { background:var(--red-pale); color:var(--red); border-radius:10px; padding:10px 12px; font-size:.88rem; margin-bottom:6px; }
.ok { background:var(--green-pale); color:var(--green); border-radius:10px; padding:12px 14px; font-size:.92rem; margin:6px 0 4px; }
button, .btn { display:block; width:100%; text-align:center; margin-top:22px; padding:14px; border:0; border-radius:50px; background:var(--dark); color:var(--white); font:inherit; font-weight:700; font-size:1rem; cursor:pointer; }
button:hover, .btn:hover { background:#222; }
.btn.ghost { background:transparent; color:var(--dark); border:2px solid rgba(14,14,14,.25); margin-top:12px; }
.links { display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; margin-top:18px; font-size:.86rem; }
.links a { color:var(--blue); font-weight:600; }
.note { margin-top:20px; padding-top:16px; border-top:1px solid var(--border); color:var(--mid); font-size:.8rem; }
dl { display:grid; grid-template-columns:auto 1fr; gap:8px 16px; margin:18px 0 4px; font-size:.92rem; }
dt { color:var(--mid); }
dd { font-weight:600; text-align:right; word-break:break-word; }
[hidden] { display:none !important; }
</style>
</head>
<body>
<header>
    <div class="header-inner">
        <a href="index.php" class="logo">
            <img src="assets/images/logo.webp" alt="Maru Quick" onerror="this.style.display='none';this.nextElementSibling.style.display='block'">
            <span class="logo-fallback" style="display:none;">Maru<span>Quick</span></span>
        </a>
        <a href="supply_portal.php#maru-power" class="back">← Back to Maru Power</a>
    </div>
</header>
<main>
<?php
}

function mp_foot(): void
{
    echo "</main>\n</body>\n</html>\n";
}

const MP_BOLT = '<svg fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>';
