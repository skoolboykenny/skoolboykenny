-- Maru Vend schema (MariaDB 10.11). All money is BIGINT thebe (1 BWP = 100 thebe).
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS settings (
  name        VARCHAR(64) PRIMARY KEY,
  value       VARCHAR(512) NOT NULL,
  updated_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB WITH SYSTEM VERSIONING;

CREATE TABLE IF NOT EXISTS designated_areas (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  district    VARCHAR(80) NOT NULL,
  village     VARCHAR(120) NOT NULL,
  target_date DATE NULL,
  live_date   DATE NULL,
  status      ENUM('planned','live') NOT NULL DEFAULT 'planned'
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS merchants (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  code          VARCHAR(32) NOT NULL UNIQUE,
  name          VARCHAR(120) NOT NULL,
  area_id       INT NULL,
  kyc_status    ENUM('pending','verified','rejected') NOT NULL DEFAULT 'pending',
  value_limit   BIGINT NOT NULL DEFAULT 0,      -- max single sale, thebe (0 = global limit)
  daily_limit   BIGINT NOT NULL DEFAULT 0,      -- 0 = unlimited
  fee_share_bp  INT NOT NULL DEFAULT 0,         -- merchant share of service fee, basis points
  active        TINYINT(1) NOT NULL DEFAULT 1,
  FOREIGN KEY (area_id) REFERENCES designated_areas(id)
) ENGINE=InnoDB WITH SYSTEM VERSIONING;

CREATE TABLE IF NOT EXISTS channels (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  merchant_id   INT NOT NULL,
  type          ENUM('POS','APP','WEB','USSD') NOT NULL,
  is_24h        TINYINT(1) NOT NULL DEFAULT 0,
  api_key       VARCHAR(64) NOT NULL UNIQUE,
  api_secret    VARCHAR(128) NOT NULL,          -- HMAC secret; stored encrypted at rest in production
  active        TINYINT(1) NOT NULL DEFAULT 1,
  FOREIGN KEY (merchant_id) REFERENCES merchants(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS vend_sales (
  id                     BIGINT AUTO_INCREMENT PRIMARY KEY,
  merchant_id            INT NOT NULL,
  channel_id             INT NOT NULL,
  idempotency_key        VARCHAR(64) NOT NULL,
  receipt_no             VARCHAR(32) NOT NULL,
  client_sale_id         CHAR(26) NOT NULL,     -- ULID sent to the provider; reused on every retry/advice
  meter_number           VARCHAR(20) NOT NULL,
  customer_name          VARCHAR(120) NULL,
  msisdn                 VARCHAR(15) NULL,      -- customer phone for SMS token delivery
  amount_thebe           BIGINT NOT NULL CHECK (amount_thebe > 0),
  state                  VARCHAR(20) NOT NULL,  -- cache only; sale_events is the record of truth
  provider               VARCHAR(20) NOT NULL,
  provider_ref           VARCHAR(64) NULL,
  fault_code             VARCHAR(32) NULL,
  fault_type             VARCHAR(32) NULL,
  attempts               INT NOT NULL DEFAULT 0,
  quote_expires_at       DATETIME(6) NULL,
  created_at             DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  submitted_at           DATETIME(6) NULL,
  resolved_at            DATETIME(6) NULL,
  UNIQUE KEY uq_idem (merchant_id, idempotency_key),
  UNIQUE KEY uq_receipt (receipt_no),
  UNIQUE KEY uq_client_sale (client_sale_id),
  KEY ix_state (state),
  KEY ix_meter (meter_number),
  FOREIGN KEY (merchant_id) REFERENCES merchants(id),
  FOREIGN KEY (channel_id) REFERENCES channels(id)
) ENGINE=InnoDB;

-- Append-only history: the source for point-in-time reports. App user gets INSERT/SELECT only.
CREATE TABLE IF NOT EXISTS sale_events (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  sale_id     BIGINT NOT NULL,
  seq         INT NOT NULL,
  from_state  VARCHAR(20) NULL,
  to_state    VARCHAR(20) NOT NULL,
  cause       VARCHAR(255) NOT NULL,
  fault_code  VARCHAR(32) NULL,
  actor       VARCHAR(64) NOT NULL,
  at          DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_sale_seq (sale_id, seq),
  KEY ix_at (at),
  FOREIGN KEY (sale_id) REFERENCES vend_sales(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS vend_tokens (
  sale_id          BIGINT PRIMARY KEY,
  token            VARCHAR(40) NOT NULL,
  key_change_1     VARCHAR(40) NULL,
  key_change_2     VARCHAR(40) NULL,
  kwh              DECIMAL(12,2) NOT NULL,
  unit_rate_thebe  BIGINT NULL,
  cost_units_thebe BIGINT NOT NULL,
  fixed_charge_thebe BIGINT NOT NULL,
  gov_levy_thebe   BIGINT NOT NULL,
  vat_thebe        BIGINT NOT NULL,
  tariff_index     VARCHAR(20) NULL,
  total_thebe      BIGINT NOT NULL,
  issued_at        DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  FOREIGN KEY (sale_id) REFERENCES vend_sales(id)
) ENGINE=InnoDB;

-- Raw provider traffic (tokens masked) for dispute resolution.
CREATE TABLE IF NOT EXISTS vend_messages (
  id           BIGINT AUTO_INCREMENT PRIMARY KEY,
  sale_id      BIGINT NOT NULL,
  operation    VARCHAR(32) NOT NULL,
  direction    ENUM('req','resp') NOT NULL,
  http_status  INT NULL,
  body         MEDIUMTEXT NOT NULL,
  body_sha256  CHAR(64) NOT NULL,
  at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  KEY ix_sale (sale_id)
) ENGINE=InnoDB;

-- Float: one position row guarded by CHECK constraints, plus an append-only ledger.
CREATE TABLE IF NOT EXISTS float_position (
  id         TINYINT PRIMARY KEY CHECK (id = 1),
  available  BIGINT NOT NULL CHECK (available >= 0),
  reserved   BIGINT NOT NULL CHECK (reserved >= 0),
  last_deposit_thebe BIGINT NOT NULL DEFAULT 0
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS float_ledger (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  sale_id       BIGINT NULL,
  deposit_id    BIGINT NULL,
  entry_type    ENUM('deposit','reserve','settle','release','refund','fee') NOT NULL,
  amount_thebe  BIGINT NOT NULL,
  available_after BIGINT NOT NULL,
  reserved_after  BIGINT NOT NULL,
  created_at    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_sale_entry (sale_id, entry_type),
  KEY ix_created (created_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS bpc_deposits (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  amount_thebe  BIGINT NOT NULL CHECK (amount_thebe > 0),
  bank_ref      VARCHAR(64) NOT NULL UNIQUE,
  deposited_at  DATETIME(6) NOT NULL,
  confirmed_by  VARCHAR(64) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS queue_jobs (
  id           BIGINT AUTO_INCREMENT PRIMARY KEY,
  sale_id      BIGINT NOT NULL,
  action       ENUM('vend','advice') NOT NULL,
  attempts     INT NOT NULL DEFAULT 0,
  next_run_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  locked_by    VARCHAR(64) NULL,
  locked_at    DATETIME(6) NULL,
  done         TINYINT(1) NOT NULL DEFAULT 0,
  KEY ix_ready (done, next_run_at),
  FOREIGN KEY (sale_id) REFERENCES vend_sales(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS approvals (
  id           BIGINT AUTO_INCREMENT PRIMARY KEY,
  action       VARCHAR(64) NOT NULL,
  payload      JSON NOT NULL,
  payload_hash CHAR(64) NOT NULL,
  maker        VARCHAR(64) NOT NULL,
  checker      VARCHAR(64) NULL,
  status       ENUM('pending','approved','rejected','expired') NOT NULL DEFAULT 'pending',
  created_at   DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  decided_at   DATETIME(6) NULL,
  CONSTRAINT chk_four_eyes CHECK (checker IS NULL OR checker <> maker)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS audit_log (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  actor       VARCHAR(64) NOT NULL,
  role        VARCHAR(32) NOT NULL,
  action      VARCHAR(64) NOT NULL,
  entity      VARCHAR(64) NOT NULL,
  entity_id   VARCHAR(64) NULL,
  old_value   TEXT NULL,
  new_value   TEXT NULL,
  ip          VARCHAR(45) NULL,
  created_at  DATETIME(6) NOT NULL,
  prev_hash   CHAR(64) NOT NULL,
  hash        CHAR(64) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS support_tickets (
  id           BIGINT AUTO_INCREMENT PRIMARY KEY,
  sale_id      BIGINT NULL,
  meter_number VARCHAR(20) NULL,
  channel      VARCHAR(10) NULL,
  issue        TEXT NOT NULL,
  agent        VARCHAR(64) NULL,
  opened_at    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  resolved_at  DATETIME(6) NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS receipt_seq (
  id BIGINT AUTO_INCREMENT PRIMARY KEY
) ENGINE=InnoDB;

-- Global submission rate limiter shared by all workers (clause 7.6).
CREATE TABLE IF NOT EXISTS rate_limiter (
  id        TINYINT PRIMARY KEY CHECK (id = 1),
  next_slot DOUBLE NOT NULL
) ENGINE=InnoDB;

-- Signed checkpoints of the audit chain head. Copies are also written outside the DB.
CREATE TABLE IF NOT EXISTS audit_anchors (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  last_id     BIGINT NOT NULL,
  head_hash   CHAR(64) NOT NULL,
  row_count   BIGINT NOT NULL,
  signature   CHAR(64) NOT NULL,
  created_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;

-- Back-office and BPC dashboard users. All logins need password + TOTP code (MFA).
CREATE TABLE IF NOT EXISTS users (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  username      VARCHAR(64) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  role          ENUM('admin','finance','support','bpc_viewer') NOT NULL,
  totp_secret   VARCHAR(64) NOT NULL,
  active        TINYINT(1) NOT NULL DEFAULT 1
) ENGINE=InnoDB WITH SYSTEM VERSIONING;

-- Single-row lock and pointer to the audit chain head. Every audit write locks this row, so
-- concurrent writers are strictly serialised and each new row links to the true previous row.
CREATE TABLE IF NOT EXISTS audit_head (
  id        TINYINT PRIMARY KEY CHECK (id = 1),
  last_hash CHAR(64) NOT NULL
) ENGINE=InnoDB;

-- Upgrade path for databases created before msisdn existed.
ALTER TABLE vend_sales ADD COLUMN IF NOT EXISTS msisdn VARCHAR(15) NULL AFTER customer_name;

-- SMS to customers (token delivery, failure notices). Sent by `bin/mv sms` through the SMS provider.
CREATE TABLE IF NOT EXISTS sms_outbox (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  sale_id     BIGINT NULL,
  msisdn      VARCHAR(15) NOT NULL,
  body        VARCHAR(480) NOT NULL,
  status      ENUM('queued','sent','failed') NOT NULL DEFAULT 'queued',
  attempts    INT NOT NULL DEFAULT 0,
  provider_ref VARCHAR(64) NULL,
  created_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  sent_at     DATETIME(6) NULL,
  KEY ix_status (status),
  KEY ix_msisdn (msisdn)
) ENGINE=InnoDB;

-- XMLVend 2.1 message identifiers (NRS 009-6-10 5.2.4.3). Allocated and stored BEFORE a request is
-- sent, so a last-response advice can always name the exact request. Each request gets a new
-- msgID (the server rejects duplicates); advice names the most recent credit vend for the sale.
CREATE TABLE IF NOT EXISTS xmlvend_messages (
  id             BIGINT AUTO_INCREMENT PRIMARY KEY,
  client_sale_id VARCHAR(32) NOT NULL,
  operation      VARCHAR(24) NOT NULL,
  terminal_id    VARCHAR(40) NOT NULL,
  msg_datetime   CHAR(14) NOT NULL,
  msg_unique     INT NOT NULL,
  created_at     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_msgid (terminal_id, msg_datetime, msg_unique),
  KEY ix_sale (client_sale_id, operation),
  KEY ix_terminal (terminal_id, id)
) ENGINE=InnoDB;
