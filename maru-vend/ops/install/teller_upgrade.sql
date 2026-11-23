-- Teller portal: add to an existing Maru Vend database (e.g. maruquic_maru_vend).
-- phpMyAdmin: click the Maru Vend database, then SQL, paste this, Go. Run it ONCE.
-- Works on MariaDB and MySQL 8.
--
-- Creates:
--   * the tellers table (each teller signs in with a username and PIN)
--   * a column on sales recording which teller sold it
--   * the till (POS channel) for outlet 1, Maru Quick, so tellers' sales use the outlet's float
--   * the first manager:  username  manager   temporary PIN  (sent separately; change it on first sign-in)

CREATE TABLE IF NOT EXISTS tellers (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  merchant_id    INT NOT NULL,
  username       VARCHAR(40) NOT NULL UNIQUE,
  name           VARCHAR(120) NOT NULL,
  role           ENUM('teller','manager') NOT NULL DEFAULT 'teller',
  pin_hash       VARCHAR(255) NOT NULL,
  active         TINYINT(1) NOT NULL DEFAULT 1,
  failed_logins  INT NOT NULL DEFAULT 0,
  locked_until   DATETIME(6) NULL,
  last_login_at  DATETIME(6) NULL,
  created_at     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  FOREIGN KEY (merchant_id) REFERENCES merchants(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

ALTER TABLE vend_sales ADD COLUMN teller_id INT NULL AFTER portal_user_id;

INSERT INTO channels (merchant_id, type, is_24h, api_key, api_secret)
SELECT 1, 'POS', 0, 'maru-teller', SHA2(CONCAT(UUID(), RAND(), NOW(6)), 256) FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM channels WHERE merchant_id = 1 AND type = 'POS');

INSERT IGNORE INTO tellers (merchant_id, username, name, role, pin_hash)
VALUES (1, 'manager', 'Outlet manager', 'manager', '$2y$10$YAaEGUp8xLwDkOwuYlCYbefOkcxuqhVURml25MOaGZh/5b0BOnDzi');
