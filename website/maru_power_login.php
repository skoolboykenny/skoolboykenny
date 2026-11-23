<?php
/*
 * Maru Power login on the Maru Quick website. Checks the email and password against power_users in the
 * Maru Quick database (separate from the Supply Portal login). Then opens the Maru Power portal with a
 * signed one-time ticket if the portal is online, or the account page on this site if it is not yet.
 */
require_once __DIR__ . '/maru_power_lib.php';
mp_session();

if (!empty($_SESSION['mp_uid']) && $_SERVER['REQUEST_METHOD'] !== 'POST') {
    header('Location: maru_power_account.php', true, 303);
    exit();
}
$error = '';
$email = '';
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $email = strtolower(trim((string) ($_POST['email'] ?? '')));
    $_SESSION['mp_tries'] = array_values(array_filter($_SESSION['mp_tries'] ?? [], function ($t) { return $t > time() - 900; }));
    if (!mp_csrf_ok()) {
        $error = 'Your session expired. Please try again.';
    } elseif (count($_SESSION['mp_tries']) >= 5) {
        $error = 'Too many attempts. Please wait 15 minutes and try again.';
    } else {
        try {
            $st = mp_db()->prepare('SELECT id, password_hash FROM power_users WHERE email = ? LIMIT 1');
            $st->execute([$email]);
            $u = $st->fetch();
            if ($u && password_verify((string) ($_POST['password'] ?? ''), $u['password_hash'])) {
                unset($_SESSION['mp_tries']);
                mp_signed_in((int) $u['id']);
            }
            $_SESSION['mp_tries'][] = time();
            usleep(300000);
            $error = 'Email or password is incorrect.';
        } catch (Throwable $ex) {
            error_log('maru_power_login.php: ' . $ex->getMessage());
            $error = 'We could not sign you in right now. Please try again shortly.';
        }
    }
}
mp_head('Maru Power Login');
?>
    <form class="card" method="post" autocomplete="on">
        <span class="tag"><?= MP_BOLT ?>Maru Power</span>
        <h1>Log in to Maru Power</h1>
        <p class="sub">Your meters, tokens and spend in Pula, for your home or business.</p>
        <?php if ($error): ?><div class="err" role="alert"><?= mp_e($error) ?></div><?php endif; ?>
        <input type="hidden" name="csrf" value="<?= mp_e($_SESSION['mp_csrf']) ?>">
        <label for="email">Email</label>
        <input id="email" name="email" type="email" autocomplete="email" required value="<?= mp_e($email) ?>">
        <label for="password">Password</label>
        <input id="password" name="password" type="password" autocomplete="current-password" required>
        <button type="submit">Log in</button>
        <div class="links">
            <a href="maru_power_signup.php?type=household">Create household account</a>
            <a href="maru_power_signup.php?type=business">Create business account</a>
        </div>
        <p class="note">This is your Maru Power login. It is separate from your Supply Portal login.</p>
    </form>
<?php mp_foot();
