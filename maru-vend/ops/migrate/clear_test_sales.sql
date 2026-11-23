-- Clear test sales before going live.
--
-- Run in phpMyAdmin > SQL. Change the two names if yours differ:
--   maruquic_maruvend        the Maru Vend database
--   maruquic_marugroupdata   the Maru Quick website database (power_users)
--
-- REMOVES (test data):
--   every sale, its tokens, history, payments, queue jobs and messages to BPC;
--   SMS sent for those sales; the float and its ledger, and the test deposits (start again at P0.00);
--   receipt numbers restart at 1;
--   the two demo Maru Power accounts (demo.household@ / demo.business@maruquick.co.bw) and their meters.
--
-- KEEPS:
--   merchants, outlets/tills and their API keys, settings, operator logins, districts;
--   every other Maru Power account, and the meters linked to them;
--   the audit log. It is a hash chain, so it is never edited; its old entries simply refer to
--   test sales that no longer exist.
--
-- After this, record the real BPC deposit in the dashboard before selling.
-- Make a backup first: phpMyAdmin > maruquic_maruvend > Export.

USE maruquic_maruvend;

DELETE FROM maruquic_maruvend.queue_jobs;
DELETE FROM maruquic_maruvend.payments;
DELETE FROM maruquic_maruvend.vend_tokens;
DELETE FROM maruquic_maruvend.vend_messages;
DELETE FROM maruquic_maruvend.xmlvend_messages;
DELETE FROM maruquic_maruvend.sale_events;
DELETE FROM maruquic_maruvend.sms_outbox;
DELETE FROM maruquic_maruvend.support_tickets;
DELETE FROM maruquic_maruvend.float_ledger;
DELETE FROM maruquic_maruvend.vend_sales;
DELETE FROM maruquic_maruvend.bpc_deposits;
DELETE FROM maruquic_maruvend.receipt_seq;
DELETE FROM maruquic_maruvend.portal_sso_nonces;
DELETE FROM maruquic_maruvend.portal_codes;

UPDATE maruquic_maruvend.float_position SET available = 0, reserved = 0, last_deposit_thebe = 0 WHERE id = 1;

ALTER TABLE maruquic_maruvend.vend_sales AUTO_INCREMENT = 1;
ALTER TABLE maruquic_maruvend.receipt_seq AUTO_INCREMENT = 1;
ALTER TABLE maruquic_maruvend.sale_events AUTO_INCREMENT = 1;
ALTER TABLE maruquic_maruvend.float_ledger AUTO_INCREMENT = 1;
ALTER TABLE maruquic_maruvend.bpc_deposits AUTO_INCREMENT = 1;
ALTER TABLE maruquic_maruvend.queue_jobs AUTO_INCREMENT = 1;
ALTER TABLE maruquic_maruvend.payments AUTO_INCREMENT = 1;

-- Demo Maru Power accounts: their meters first (Maru Vend), then the accounts (Maru Quick).
DELETE pm FROM maruquic_maruvend.portal_meters pm
JOIN maruquic_marugroupdata.power_users u ON u.id = pm.user_id
WHERE u.email IN ('demo.household@maruquick.co.bw', 'demo.business@maruquick.co.bw');
DELETE c FROM maruquic_marugroupdata.power_codes c
JOIN maruquic_marugroupdata.power_users u ON u.id = c.user_id
WHERE u.email IN ('demo.household@maruquick.co.bw', 'demo.business@maruquick.co.bw');
DELETE FROM maruquic_marugroupdata.power_users
WHERE email IN ('demo.household@maruquick.co.bw', 'demo.business@maruquick.co.bw');
