-- Maru Power customer accounts in the Maru Quick website database (maruquic_marugroupdata).
-- Run once, e.g. in phpMyAdmin > SQL. Creates two new tables and touches nothing else:
-- the Supply Portal's supply_* tables are not changed, and the two logins stay separate.
--
-- Meters, tokens and sales stay in Maru Vend and refer to these accounts by id.

CREATE TABLE IF NOT EXISTS power_users (
  id             BIGINT AUTO_INCREMENT PRIMARY KEY,
  name           VARCHAR(120) NOT NULL,
  account_type   ENUM('household','business') NOT NULL DEFAULT 'household',
  company_name   VARCHAR(160) NULL,
  company_reg    VARCHAR(40) NULL,            -- CIPA UIN
  vat_no         VARCHAR(40) NULL,            -- BURS VAT number, optional
  email          VARCHAR(190) NOT NULL UNIQUE,
  msisdn         VARCHAR(15) NULL UNIQUE,     -- set only once verified by SMS code
  password_hash  VARCHAR(255) NOT NULL,       -- PHP password_hash(); never the password itself
  created_at     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS power_codes (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id     BIGINT NOT NULL,
  purpose     VARCHAR(16) NOT NULL,
  target      VARCHAR(64) NOT NULL,
  code_hash   CHAR(64) NOT NULL,
  attempts    INT NOT NULL DEFAULT 0,
  expires_at  DATETIME(6) NOT NULL,
  used_at     DATETIME(6) NULL,
  KEY ix_user (user_id, purpose),
  FOREIGN KEY (user_id) REFERENCES power_users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Maru Vend connects with its own database user, limited to these two tables:
--   CREATE USER 'marupower'@'<maru vend server>' IDENTIFIED BY '<strong password>';
--   GRANT SELECT, INSERT, UPDATE ON maruquic_marugroupdata.power_users TO 'marupower'@'<maru vend server>';
--   GRANT SELECT, INSERT, UPDATE ON maruquic_marugroupdata.power_codes TO 'marupower'@'<maru vend server>';
