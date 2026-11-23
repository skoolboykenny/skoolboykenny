<?php
/* Signed-in Maru Power customer: account details, and the way into the portal once it is online. */
require_once __DIR__ . '/maru_power_lib.php';
mp_session();

if ($_SERVER['REQUEST_METHOD'] === 'POST' && mp_csrf_ok()) {
    if (($_POST['action'] ?? '') === 'logout') {
        $_SESSION = [];
        session_destroy();
        header('Location: maru_power_login.php', true, 303);
        exit();
    }
    if (($_POST['action'] ?? '') === 'portal' && !empty($_SESSION['mp_uid'])) {
        mp_signed_in((int) $_SESSION['mp_uid']);
    }
}
if (empty($_SESSION['mp_uid'])) {
    header('Location: maru_power_login.php', true, 303);
    exit();
}
try {
    $st = mp_db()->prepare('SELECT name, account_type, company_name, company_reg, vat_no, email, created_at FROM power_users WHERE id = ?');
    $st->execute([(int) $_SESSION['mp_uid']]);
    $u = $st->fetch();
} catch (Throwable $ex) {
    error_log('maru_power_account.php: ' . $ex->getMessage());
    $u = null;
}
if (!$u) {
    $_SESSION = [];
    header('Location: maru_power_login.php', true, 303);
    exit();
}
$portal = mp_portal_url();
mp_head('My Maru Power account');
?>
    <div class="card">
        <span class="tag"><?= MP_BOLT ?>Maru Power</span>
        <h1>Welcome, <?= mp_e(explode(' ', $u['name'])[0]) ?>!</h1>
        <div class="ok">Your <?= $u['account_type'] === 'business' ? 'business' : 'household' ?> account is ready.</div>
        <dl>
            <dt>Name</dt><dd><?= mp_e($u['name']) ?></dd>
            <dt>Email</dt><dd><?= mp_e($u['email']) ?></dd>
            <dt>Account type</dt><dd><?= $u['account_type'] === 'business' ? 'Business' : 'Household' ?></dd>
            <?php if ($u['account_type'] === 'business'): ?>
            <dt>Company</dt><dd><?= mp_e($u['company_name']) ?></dd>
            <dt>CIPA number</dt><dd><?= mp_e($u['company_reg']) ?></dd>
            <?php if ($u['vat_no']): ?><dt>VAT number</dt><dd><?= mp_e($u['vat_no']) ?></dd><?php endif; ?>
            <?php endif; ?>
            <dt>Member since</dt><dd><?= mp_e(date('j M Y', strtotime($u['created_at']))) ?></dd>
        </dl>
        <form method="post">
            <input type="hidden" name="csrf" value="<?= mp_e($_SESSION['mp_csrf']) ?>">
            <?php if ($portal): ?>
                <button name="action" value="portal">Open Maru Power</button>
            <?php else: ?>
                <p class="note">Buying electricity, linking meters and your token history open here soon. We will let you know by email at <?= mp_e($u['email']) ?>.</p>
            <?php endif; ?>
            <button name="action" value="logout" class="btn ghost">Log out</button>
        </form>
    </div>
<?php mp_foot();
