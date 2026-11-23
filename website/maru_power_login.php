<?php
/*
 * Maru Power login on the Maru Quick website.
 *
 * Checks the email and password against power_users in the Maru Quick database (separate from the
 * Supply Portal's supply_users), then opens the Maru Power portal already signed in, using a signed
 * ticket that works once and only for 60 seconds. The password never leaves this server.
 *
 * Needs, in includes/mq_secrets.php (kept outside the web root, never committed):
 *   define('MQ_DB_USER', '...');            // already there
 *   define('MQ_DB_PASS', '...');            // already there
 *   define('MQ_POWER_SSO_SECRET', '...');   // same value as MV_SSO_SECRET on the Maru Power server, 32+ characters
 *   define('MQ_POWER_URL', 'https://.../power');
 */
require_once __DIR__ . '/includes/mq_secrets.php';

$secure = !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off';
session_name('mq_power_login');
session_start(['cookie_httponly' => true, 'cookie_samesite' => 'Lax', 'cookie_secure' => $secure]);

$powerUrl = rtrim(defined('MQ_POWER_URL') ? MQ_POWER_URL : (getenv('MARU_POWER_URL') ?: 'http://127.0.0.1:8080/power'), '/');
$ssoSecret = defined('MQ_POWER_SSO_SECRET') ? MQ_POWER_SSO_SECRET : (string) getenv('MQ_POWER_SSO_SECRET');
$e = function ($s) { return htmlspecialchars((string) $s, ENT_QUOTES, 'UTF-8'); };

if (empty($_SESSION['csrf'])) {
    $_SESSION['csrf'] = bin2hex(random_bytes(16));
}

/** Ticket format must match maru-vend/src/Portal/Sso.php. */
function mq_power_ticket(string $secret, int $uid): string
{
    $body = rtrim(strtr(base64_encode(json_encode(['uid' => $uid, 'exp' => time() + 60, 'n' => bin2hex(random_bytes(16))])), '+/', '-_'), '=');
    return $body . '.' . hash_hmac('sha256', $body, $secret);
}

$error = '';
$email = '';
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $email = strtolower(trim((string) ($_POST['email'] ?? '')));
    $password = (string) ($_POST['password'] ?? '');
    $_SESSION['tries'] = array_values(array_filter($_SESSION['tries'] ?? [], function ($t) { return $t > time() - 900; }));

    if (!hash_equals($_SESSION['csrf'], (string) ($_POST['csrf'] ?? ''))) {
        $error = 'Your session expired. Please try again.';
    } elseif (count($_SESSION['tries']) >= 5) {
        $error = 'Too many attempts. Please wait 15 minutes and try again.';
    } elseif (strlen($ssoSecret) < 32) {
        error_log('maru_power_login.php: MQ_POWER_SSO_SECRET is not set (32+ characters needed)');
        $error = 'Maru Power sign-in is not available right now. Please try again later.';
    } else {
        try {
            $pdo = new PDO('mysql:host=localhost;port=3306;dbname=maruquic_marugroupdata;charset=utf8mb4', MQ_DB_USER, MQ_DB_PASS, [
                PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION, PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC, PDO::ATTR_EMULATE_PREPARES => false,
            ]);
            $st = $pdo->prepare('SELECT id, password_hash FROM power_users WHERE email = ? LIMIT 1');
            $st->execute([$email]);
            $u = $st->fetch();
            if ($u && password_verify($password, $u['password_hash'])) {
                session_regenerate_id(true);
                unset($_SESSION['tries']);
                header('Referrer-Policy: no-referrer');
                header('Location: ' . $powerUrl . '/sso?t=' . rawurlencode(mq_power_ticket($ssoSecret, (int) $u['id'])), true, 303);
                exit();
            }
            $_SESSION['tries'][] = time();
            usleep(300000);
            $error = 'Email or password is incorrect.';
        } catch (Throwable $ex) {
            error_log('maru_power_login.php: ' . $ex->getMessage());
            $error = 'We could not sign you in right now. Please try again shortly.';
        }
    }
}
header('X-Frame-Options: DENY');
?><!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Maru Quick — Maru Power Login</title>
<link rel="icon" type="image/png" href="favicon.png">
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@600;700;800;900&family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&display=swap" rel="stylesheet">
<style>
*, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }
a { text-decoration:none; color:inherit; }
:root { --yellow:#F5C518; --yellow-dk:#D4A900; --yellow-pale:#FFFBEA; --dark:#0E0E0E; --mid:#6B7280; --white:#FFFFFF; --blue:#1A6BFF; --border:#E5E7EB; --red:#B42318; --red-pale:#FDECEC; --fh:'Sora', sans-serif; --fb:'DM Sans', sans-serif; --px:clamp(20px, 5vw, 72px); }
body { font-family:var(--fb); background:var(--yellow); color:var(--dark); line-height:1.6; min-height:100vh; display:flex; flex-direction:column; }
header { background:var(--white); border-bottom:1px solid var(--border); }
.header-inner { max-width:1280px; margin:0 auto; padding:0 var(--px); height:70px; display:flex; align-items:center; justify-content:space-between; }
.logo img { height:44px; width:auto; }
.logo-fallback { font-family:var(--fh); font-size:1.3rem; font-weight:800; }
.logo-fallback span { color:var(--yellow-dk); }
.back { font-size:.88rem; font-weight:600; color:var(--mid); }
main { flex:1; display:grid; place-items:center; padding:48px 20px; position:relative; overflow:hidden; }
main::before { content:''; position:absolute; top:-120px; right:-120px; width:480px; height:480px; border-radius:50%; background:rgba(255,255,255,.14); }
.card { position:relative; width:100%; max-width:440px; background:var(--white); border-radius:24px; padding:36px 32px; box-shadow:0 24px 60px rgba(0,0,0,.12); }
.tag { display:inline-flex; align-items:center; gap:7px; background:var(--yellow-pale); color:var(--yellow-dk); padding:5px 12px; border-radius:50px; font-size:.75rem; font-weight:700; letter-spacing:.05em; text-transform:uppercase; margin-bottom:16px; }
.tag svg { width:13px; height:13px; }
h1 { font-family:var(--fh); font-size:1.7rem; font-weight:800; letter-spacing:-.02em; margin-bottom:6px; }
.sub { color:var(--mid); font-size:.92rem; margin-bottom:24px; }
label { display:block; font-weight:600; font-size:.85rem; margin:14px 0 6px; }
input { width:100%; font:inherit; font-size:1rem; padding:13px 14px; border:1.5px solid var(--border); border-radius:12px; }
input:focus { outline:none; border-color:var(--yellow); box-shadow:0 0 0 3px rgba(245,197,24,.25); }
.err { background:var(--red-pale); color:var(--red); border-radius:10px; padding:10px 12px; font-size:.88rem; margin-bottom:6px; }
button { width:100%; margin-top:22px; padding:14px; border:0; border-radius:50px; background:var(--dark); color:var(--white); font:inherit; font-weight:700; font-size:1rem; cursor:pointer; }
button:hover { background:#222; }
.links { display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; margin-top:18px; font-size:.86rem; }
.links a { color:var(--blue); font-weight:600; }
.note { margin-top:20px; padding-top:16px; border-top:1px solid var(--border); color:var(--mid); font-size:.8rem; }
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
    <form class="card" method="post" autocomplete="on">
        <span class="tag"><svg fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>Maru Power</span>
        <h1>Log in to Maru Power</h1>
        <p class="sub">Your meters, tokens and spend in Pula, for your home or business.</p>
        <?php if ($error): ?><div class="err" role="alert"><?= $e($error) ?></div><?php endif; ?>
        <input type="hidden" name="csrf" value="<?= $e($_SESSION['csrf']) ?>">
        <label for="email">Email</label>
        <input id="email" name="email" type="email" autocomplete="email" required value="<?= $e($email) ?>">
        <label for="password">Password</label>
        <input id="password" name="password" type="password" autocomplete="current-password" required>
        <button type="submit">Log in</button>
        <div class="links">
            <a href="<?= $e($powerUrl . '#/login/signup-household') ?>">Create household account</a>
            <a href="<?= $e($powerUrl . '#/login/signup-business') ?>">Create business account</a>
        </div>
        <p class="note">This is your Maru Power login. It is separate from your Supply Portal login.</p>
    </form>
</main>
</body>
</html>
