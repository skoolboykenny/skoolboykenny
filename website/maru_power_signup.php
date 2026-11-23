<?php
/* Create a Maru Power account (household or business). Saved in the Maru Quick database, power_users. */
require_once __DIR__ . '/maru_power_lib.php';
mp_session();

$type = ($_GET['type'] ?? $_POST['account_type'] ?? 'household') === 'business' ? 'business' : 'household';
$in = ['name' => '', 'email' => '', 'company_name' => '', 'company_reg' => '', 'vat_no' => ''];
$error = '';
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $in = array_merge($in, array_map('strval', array_intersect_key($_POST, $in)));
    if (!mp_csrf_ok()) {
        $error = 'Your session expired. Please try again.';
    } else {
        try {
            mp_signed_in(mp_create_account($_POST + ['account_type' => $type]));
        } catch (InvalidArgumentException $ex) {
            $error = $ex->getMessage();
        } catch (Throwable $ex) {
            error_log('maru_power_signup.php: ' . $ex->getMessage());
            $error = 'We could not create your account right now. Please try again shortly.';
        }
    }
}
mp_head('Create a Maru Power account');
?>
    <form class="card" method="post" autocomplete="on">
        <span class="tag"><?= MP_BOLT ?>Maru Power</span>
        <h1>Create your Maru Power account</h1>
        <p class="sub">Buy prepaid electricity and see every token for every meter, with all amounts in Pula (BWP).</p>
        <?php if ($error): ?><div class="err" role="alert"><?= mp_e($error) ?></div><?php endif; ?>
        <input type="hidden" name="csrf" value="<?= mp_e($_SESSION['mp_csrf']) ?>">

        <div class="types" role="radiogroup" aria-label="Account type">
            <label><input type="radio" name="account_type" value="household" <?= $type === 'household' ? 'checked' : '' ?>><b>Household</b><span>Your home and family's homes</span></label>
            <label><input type="radio" name="account_type" value="business" <?= $type === 'business' ? 'checked' : '' ?>><b>Business</b><span>Shops, offices, many sites</span></label>
        </div>

        <div id="biz" <?= $type === 'business' ? '' : 'hidden' ?>>
            <label for="cn">Registered company name</label>
            <input id="cn" name="company_name" autocomplete="organization" value="<?= mp_e($in['company_name']) ?>">
            <label for="cr">Company registration number <small>CIPA UIN, e.g. BW00001234567</small></label>
            <input id="cr" name="company_reg" autocomplete="off" value="<?= mp_e($in['company_reg']) ?>">
            <label for="vat">VAT number <small>BURS, optional</small></label>
            <input id="vat" name="vat_no" autocomplete="off" value="<?= mp_e($in['vat_no']) ?>">
        </div>

        <label for="name" id="nameLbl"><?= $type === 'business' ? 'Your full name (account administrator)' : 'Full name' ?></label>
        <input id="name" name="name" autocomplete="name" required value="<?= mp_e($in['name']) ?>">
        <label for="email">Email</label>
        <input id="email" name="email" type="email" autocomplete="email" required value="<?= mp_e($in['email']) ?>">
        <label for="pw">Password <small>at least 8 characters</small></label>
        <input id="pw" name="password" type="password" autocomplete="new-password" minlength="8" required>
        <label for="pw2">Confirm password</label>
        <input id="pw2" name="password2" type="password" autocomplete="new-password" minlength="8" required>

        <button type="submit">Create account</button>
        <div class="links"><span>Already have an account?</span><a href="maru_power_login.php">Log in</a></div>
        <p class="note">This is your Maru Power account. It is separate from your Supply Portal login.</p>
    </form>
<script>
document.querySelectorAll('input[name="account_type"]').forEach(function (r) {
    r.addEventListener('change', function () {
        var biz = r.value === 'business' && r.checked;
        document.getElementById('biz').hidden = !biz;
        document.getElementById('nameLbl').textContent = biz ? 'Your full name (account administrator)' : 'Full name';
    });
});
</script>
<?php mp_foot();
