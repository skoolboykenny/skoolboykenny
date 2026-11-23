-- Move Maru Power accounts from the Maru Vend database into the Maru Quick database.
--
-- Use after importing a Maru Vend database (e.g. the copy from your PC) into maruquic_maruvend.
-- Run in phpMyAdmin > SQL (any database selected). Change the two names below if yours differ:
--   maruquic_maruvend        the Maru Vend database
--   maruquic_marugroupdata   the Maru Quick website database (power_users)
--
-- What it does:
--   1. Copies every account in portal_users to power_users. An email already in power_users
--      (e.g. an account made on the live site) is not copied again; the existing account is kept.
--      A phone number already used by another account is left empty on the copied one.
--   2. Points the copied meters and purchases at the account ids in power_users.
--   3. Empties portal_users, so accounts exist in one place only.
-- Safe to run twice: the second run finds nothing left to move.

INSERT INTO maruquic_marugroupdata.power_users
    (name, account_type, company_name, company_reg, vat_no, email, msisdn, password_hash, created_at)
SELECT p.name, p.account_type, p.company_name, p.company_reg, p.vat_no, p.email,
       IF(EXISTS (SELECT 1 FROM maruquic_marugroupdata.power_users u2 WHERE u2.msisdn = p.msisdn), NULL, p.msisdn),
       p.password_hash, p.created_at
FROM maruquic_maruvend.portal_users p
WHERE NOT EXISTS (SELECT 1 FROM maruquic_marugroupdata.power_users u WHERE u.email = p.email);

-- Old id -> new id, by email.
CREATE TEMPORARY TABLE maruquic_maruvend.mp_account_map (old_id BIGINT PRIMARY KEY, new_id BIGINT NOT NULL)
SELECT p.id AS old_id, u.id AS new_id
FROM maruquic_maruvend.portal_users p JOIN maruquic_marugroupdata.power_users u ON u.email = p.email;

-- Two passes through a high offset, so swapped ids never collide midway.
UPDATE maruquic_maruvend.portal_meters pm JOIN maruquic_maruvend.mp_account_map m ON pm.user_id = m.old_id SET pm.user_id = m.new_id + 1000000000;
UPDATE maruquic_maruvend.portal_meters SET user_id = user_id - 1000000000 WHERE user_id >= 1000000000;
UPDATE maruquic_maruvend.vend_sales s JOIN maruquic_maruvend.mp_account_map m ON s.portal_user_id = m.old_id SET s.portal_user_id = m.new_id + 1000000000;
UPDATE maruquic_maruvend.vend_sales SET portal_user_id = portal_user_id - 1000000000 WHERE portal_user_id >= 1000000000;

DELETE FROM maruquic_maruvend.portal_codes;
DELETE FROM maruquic_maruvend.portal_users WHERE id IN (SELECT old_id FROM maruquic_maruvend.mp_account_map);
DROP TEMPORARY TABLE maruquic_maruvend.mp_account_map;
