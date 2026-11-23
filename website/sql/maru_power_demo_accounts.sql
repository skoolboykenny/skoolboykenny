-- OPTIONAL demo accounts for testing Maru Power (run after maru_power_accounts.sql).
-- Both use the password  MaruDemo#2026  — delete them before going live:
--   DELETE FROM power_users WHERE email IN ('demo.household@maruquick.co.bw', 'demo.business@maruquick.co.bw');
INSERT INTO power_users (name, account_type, email, password_hash)
VALUES ('Lethabo Molefe', 'household', 'demo.household@maruquick.co.bw', '$2y$10$pzFEAU8vBXu21rbUNGa0CuCsg05JWzpkyAJt/TL2B3L04WxRyyS0a');
INSERT INTO power_users (name, account_type, company_name, company_reg, vat_no, email, password_hash)
VALUES ('Boitumelo Kgosi', 'business', 'Kgosi Traders (Pty) Ltd', 'BW00001234567', NULL, 'demo.business@maruquick.co.bw', '$2y$10$yRt9xtSqEYXPbBncjMWuteNqbW.4vY7pQBBYGZS80JPICVjujy1qq');
