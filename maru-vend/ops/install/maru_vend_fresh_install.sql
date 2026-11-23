-- Maru Vend: fresh install for the live database (e.g. maruquic_maru_vend).
-- phpMyAdmin: click the Maru Vend database on the left, then Import this file (or paste it into SQL).
-- Creates every table, empty, plus the starting setup Maru Power needs:
--   * one merchant (Maru Quick) and the Maru Power sales channel (key maru-power, its own random secret)
--   * token source = TEST (built-in test tokens; they do not load on a real meter)
--   * a TEST float of P100,000.00 so test purchases can be made (clear it with clear_test_sales.sql)
-- Works on MariaDB and MySQL 8. Safe to run again: existing tables and rows are left as they are.

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `approvals` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `action` varchar(64) NOT NULL,
  `payload` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL CHECK (json_valid(`payload`)),
  `payload_hash` char(64) NOT NULL,
  `maker` varchar(64) NOT NULL,
  `checker` varchar(64) DEFAULT NULL,
  `status` enum('pending','approved','rejected','expired') NOT NULL DEFAULT 'pending',
  `created_at` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  `decided_at` datetime(6) DEFAULT NULL,
  PRIMARY KEY (`id`),
  CONSTRAINT `chk_four_eyes` CHECK (`checker` is null or `checker` <> `maker`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `audit_anchors` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `last_id` bigint(20) NOT NULL,
  `head_hash` char(64) NOT NULL,
  `row_count` bigint(20) NOT NULL,
  `signature` char(64) NOT NULL,
  `created_at` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `audit_head` (
  `id` tinyint(4) NOT NULL CHECK (`id` = 1),
  `last_hash` char(64) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `audit_log` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `actor` varchar(64) NOT NULL,
  `role` varchar(32) NOT NULL,
  `action` varchar(64) NOT NULL,
  `entity` varchar(64) NOT NULL,
  `entity_id` varchar(64) DEFAULT NULL,
  `old_value` text DEFAULT NULL,
  `new_value` text DEFAULT NULL,
  `ip` varchar(45) DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `prev_hash` char(64) NOT NULL,
  `hash` char(64) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `bpc_deposits` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `amount_thebe` bigint(20) NOT NULL CHECK (`amount_thebe` > 0),
  `bank_ref` varchar(64) NOT NULL,
  `deposited_at` datetime(6) NOT NULL,
  `confirmed_by` varchar(64) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `bank_ref` (`bank_ref`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `channels` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `merchant_id` int(11) NOT NULL,
  `type` enum('POS','APP','WEB','USSD') NOT NULL,
  `is_24h` tinyint(1) NOT NULL DEFAULT 0,
  `api_key` varchar(64) NOT NULL,
  `api_secret` varchar(128) NOT NULL,
  `active` tinyint(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (`id`),
  UNIQUE KEY `api_key` (`api_key`),
  KEY `merchant_id` (`merchant_id`),
  CONSTRAINT `channels_ibfk_1` FOREIGN KEY (`merchant_id`) REFERENCES `merchants` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `designated_areas` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `district` varchar(80) NOT NULL,
  `village` varchar(120) NOT NULL,
  `target_date` date DEFAULT NULL,
  `live_date` date DEFAULT NULL,
  `status` enum('planned','live') NOT NULL DEFAULT 'planned',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `float_ledger` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `sale_id` bigint(20) DEFAULT NULL,
  `deposit_id` bigint(20) DEFAULT NULL,
  `entry_type` enum('deposit','reserve','settle','release','refund','fee') NOT NULL,
  `amount_thebe` bigint(20) NOT NULL,
  `available_after` bigint(20) NOT NULL,
  `reserved_after` bigint(20) NOT NULL,
  `created_at` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_sale_entry` (`sale_id`,`entry_type`),
  KEY `ix_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `float_position` (
  `id` tinyint(4) NOT NULL CHECK (`id` = 1),
  `available` bigint(20) NOT NULL CHECK (`available` >= 0),
  `reserved` bigint(20) NOT NULL CHECK (`reserved` >= 0),
  `last_deposit_thebe` bigint(20) NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `merchants` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `code` varchar(32) NOT NULL,
  `name` varchar(120) NOT NULL,
  `area_id` int(11) DEFAULT NULL,
  `kyc_status` enum('pending','verified','rejected') NOT NULL DEFAULT 'pending',
  `value_limit` bigint(20) NOT NULL DEFAULT 0,
  `daily_limit` bigint(20) NOT NULL DEFAULT 0,
  `fee_share_bp` int(11) NOT NULL DEFAULT 0,
  `active` tinyint(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (`id`),
  UNIQUE KEY `code` (`code`),
  KEY `area_id` (`area_id`),
  CONSTRAINT `merchants_ibfk_1` FOREIGN KEY (`area_id`) REFERENCES `designated_areas` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `payments` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `sale_id` bigint(20) NOT NULL,
  `provider` varchar(32) NOT NULL,
  `payment_ref` varchar(64) NOT NULL,
  `amount_thebe` bigint(20) NOT NULL,
  `status` enum('verified','rejected','reversed') NOT NULL,
  `reason` varchar(255) DEFAULT NULL,
  `body_sha256` char(64) NOT NULL,
  `received_at` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_ref` (`provider`,`payment_ref`),
  KEY `ix_sale` (`sale_id`),
  CONSTRAINT `payments_ibfk_1` FOREIGN KEY (`sale_id`) REFERENCES `vend_sales` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `portal_codes` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `user_id` bigint(20) NOT NULL,
  `purpose` varchar(16) NOT NULL,
  `target` varchar(64) NOT NULL,
  `code_hash` char(64) NOT NULL,
  `attempts` int(11) NOT NULL DEFAULT 0,
  `expires_at` datetime(6) NOT NULL,
  `used_at` datetime(6) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_user` (`user_id`,`purpose`),
  CONSTRAINT `portal_codes_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `portal_users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `portal_meters` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `user_id` bigint(20) NOT NULL,
  `meter_number` varchar(20) NOT NULL,
  `role` enum('owner','member') NOT NULL,
  `label` varchar(60) NOT NULL,
  `site_type` enum('home','business','other') NOT NULL DEFAULT 'home',
  `linked_by` varchar(32) NOT NULL,
  `proof` varchar(64) DEFAULT NULL,
  `created_at` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_user_meter` (`user_id`,`meter_number`),
  KEY `ix_meter` (`meter_number`),
  KEY `ix_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `portal_sso_nonces` (
  `nonce` char(32) NOT NULL,
  `user_id` bigint(20) NOT NULL,
  `used_at` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  PRIMARY KEY (`nonce`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `portal_users` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `name` varchar(120) NOT NULL,
  `account_type` enum('household','business') NOT NULL DEFAULT 'household',
  `company_name` varchar(160) DEFAULT NULL,
  `company_reg` varchar(40) DEFAULT NULL,
  `vat_no` varchar(40) DEFAULT NULL,
  `email` varchar(190) NOT NULL,
  `msisdn` varchar(15) DEFAULT NULL,
  `password_hash` varchar(255) NOT NULL,
  `created_at` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  PRIMARY KEY (`id`),
  UNIQUE KEY `email` (`email`),
  UNIQUE KEY `msisdn` (`msisdn`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `queue_jobs` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `sale_id` bigint(20) NOT NULL,
  `action` enum('vend','advice') NOT NULL,
  `attempts` int(11) NOT NULL DEFAULT 0,
  `next_run_at` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  `locked_by` varchar(64) DEFAULT NULL,
  `locked_at` datetime(6) DEFAULT NULL,
  `done` tinyint(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  KEY `ix_ready` (`done`,`next_run_at`),
  KEY `sale_id` (`sale_id`),
  CONSTRAINT `queue_jobs_ibfk_1` FOREIGN KEY (`sale_id`) REFERENCES `vend_sales` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `rate_limiter` (
  `id` tinyint(4) NOT NULL CHECK (`id` = 1),
  `next_slot` double NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `receipt_seq` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `sale_events` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `sale_id` bigint(20) NOT NULL,
  `seq` int(11) NOT NULL,
  `from_state` varchar(20) DEFAULT NULL,
  `to_state` varchar(20) NOT NULL,
  `cause` varchar(255) NOT NULL,
  `fault_code` varchar(32) DEFAULT NULL,
  `actor` varchar(64) NOT NULL,
  `at` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_sale_seq` (`sale_id`,`seq`),
  KEY `ix_at` (`at`),
  CONSTRAINT `sale_events_ibfk_1` FOREIGN KEY (`sale_id`) REFERENCES `vend_sales` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `settings` (
  `name` varchar(64) NOT NULL,
  `value` varchar(512) NOT NULL,
  `updated_at` datetime(6) NOT NULL DEFAULT current_timestamp(6) ON UPDATE current_timestamp(6),
  PRIMARY KEY (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `sms_outbox` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `sale_id` bigint(20) DEFAULT NULL,
  `msisdn` varchar(15) NOT NULL,
  `body` varchar(480) NOT NULL,
  `status` enum('queued','sent','failed') NOT NULL DEFAULT 'queued',
  `attempts` int(11) NOT NULL DEFAULT 0,
  `provider_ref` varchar(64) DEFAULT NULL,
  `created_at` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  `sent_at` datetime(6) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_status` (`status`),
  KEY `ix_msisdn` (`msisdn`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `support_tickets` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `sale_id` bigint(20) DEFAULT NULL,
  `meter_number` varchar(20) DEFAULT NULL,
  `channel` varchar(10) DEFAULT NULL,
  `issue` text NOT NULL,
  `agent` varchar(64) DEFAULT NULL,
  `opened_at` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  `resolved_at` datetime(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `users` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `username` varchar(64) NOT NULL,
  `password_hash` varchar(255) NOT NULL,
  `role` enum('admin','finance','support','bpc_viewer') NOT NULL,
  `totp_secret` varchar(64) NOT NULL,
  `active` tinyint(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `vend_messages` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `sale_id` bigint(20) NOT NULL,
  `operation` varchar(32) NOT NULL,
  `direction` enum('req','resp') NOT NULL,
  `http_status` int(11) DEFAULT NULL,
  `body` mediumtext NOT NULL,
  `body_sha256` char(64) NOT NULL,
  `at` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  PRIMARY KEY (`id`),
  KEY `ix_sale` (`sale_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `vend_sales` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `merchant_id` int(11) NOT NULL,
  `channel_id` int(11) NOT NULL,
  `idempotency_key` varchar(64) NOT NULL,
  `receipt_no` varchar(32) NOT NULL,
  `client_sale_id` char(26) NOT NULL,
  `meter_number` varchar(20) NOT NULL,
  `customer_name` varchar(120) DEFAULT NULL,
  `msisdn` varchar(15) DEFAULT NULL,
  `portal_user_id` bigint(20) DEFAULT NULL,
  `amount_thebe` bigint(20) NOT NULL CHECK (`amount_thebe` > 0),
  `state` varchar(20) NOT NULL,
  `provider` varchar(20) NOT NULL,
  `provider_ref` varchar(64) DEFAULT NULL,
  `fault_code` varchar(32) DEFAULT NULL,
  `fault_type` varchar(32) DEFAULT NULL,
  `attempts` int(11) NOT NULL DEFAULT 0,
  `quote_expires_at` datetime(6) DEFAULT NULL,
  `created_at` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  `submitted_at` datetime(6) DEFAULT NULL,
  `resolved_at` datetime(6) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_idem` (`merchant_id`,`idempotency_key`),
  UNIQUE KEY `uq_receipt` (`receipt_no`),
  UNIQUE KEY `uq_client_sale` (`client_sale_id`),
  KEY `ix_state` (`state`),
  KEY `ix_meter` (`meter_number`),
  KEY `channel_id` (`channel_id`),
  CONSTRAINT `vend_sales_ibfk_1` FOREIGN KEY (`merchant_id`) REFERENCES `merchants` (`id`),
  CONSTRAINT `vend_sales_ibfk_2` FOREIGN KEY (`channel_id`) REFERENCES `channels` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `vend_tokens` (
  `sale_id` bigint(20) NOT NULL,
  `token` varchar(40) NOT NULL,
  `key_change_1` varchar(40) DEFAULT NULL,
  `key_change_2` varchar(40) DEFAULT NULL,
  `kwh` decimal(12,2) NOT NULL,
  `unit_rate_thebe` bigint(20) DEFAULT NULL,
  `cost_units_thebe` bigint(20) NOT NULL,
  `fixed_charge_thebe` bigint(20) NOT NULL,
  `gov_levy_thebe` bigint(20) NOT NULL,
  `vat_thebe` bigint(20) NOT NULL,
  `tariff_index` varchar(20) DEFAULT NULL,
  `total_thebe` bigint(20) NOT NULL,
  `issued_at` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  PRIMARY KEY (`sale_id`),
  CONSTRAINT `vend_tokens_ibfk_1` FOREIGN KEY (`sale_id`) REFERENCES `vend_sales` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE IF NOT EXISTS `xmlvend_messages` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `client_sale_id` varchar(32) NOT NULL,
  `operation` varchar(24) NOT NULL,
  `terminal_id` varchar(40) NOT NULL,
  `msg_datetime` char(14) NOT NULL,
  `msg_unique` int(11) NOT NULL,
  `answered` tinyint(1) NOT NULL DEFAULT 0,
  `recovered` mediumtext DEFAULT NULL,
  `created_at` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_msgid` (`terminal_id`,`msg_datetime`,`msg_unique`),
  KEY `ix_sale` (`client_sale_id`,`operation`),
  KEY `ix_terminal` (`terminal_id`,`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- ---------------------------------------------------------------- starting setup
INSERT IGNORE INTO float_position (id, available, reserved, last_deposit_thebe) VALUES (1, 0, 0, 0);
INSERT IGNORE INTO rate_limiter (id, next_slot) VALUES (1, 0);
INSERT IGNORE INTO audit_head (id, last_hash) VALUES (1, '0000000000000000000000000000000000000000000000000000000000000000');

INSERT IGNORE INTO settings (name, value) VALUES ('provider', 'test');

INSERT IGNORE INTO merchants (id, code, name, kyc_status, daily_limit) VALUES (1, 'MQ-POWER', 'Maru Quick', 'verified', 0);
INSERT IGNORE INTO channels (id, merchant_id, type, is_24h, api_key, api_secret)
VALUES (1, 1, 'APP', 1, 'maru-power', SHA2(CONCAT(UUID(), RAND(), NOW(6)), 256));

-- TEST float (only if no deposit has been recorded yet).
INSERT INTO bpc_deposits (amount_thebe, bank_ref, deposited_at, confirmed_by)
SELECT 10000000, 'TEST-FLOAT-001', NOW(6), 'install' FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM bpc_deposits);
INSERT INTO float_ledger (deposit_id, entry_type, amount_thebe, available_after, reserved_after)
SELECT d.id, 'deposit', 10000000, 10000000, 0 FROM bpc_deposits d
WHERE d.bank_ref = 'TEST-FLOAT-001' AND NOT EXISTS (SELECT 1 FROM float_ledger WHERE deposit_id = d.id);
UPDATE float_position SET available = 10000000, last_deposit_thebe = 10000000
WHERE id = 1 AND available = 0 AND reserved = 0 AND EXISTS (SELECT 1 FROM bpc_deposits WHERE bank_ref = 'TEST-FLOAT-001')
  AND (SELECT COUNT(*) FROM float_ledger) = 1;
