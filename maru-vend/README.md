# Maru Vend

Third-party prepaid electricity vending platform for Botswana Power Corporation (Tender 7766/26),
built by Maru Quick (Pty) Ltd.

Channels (POS, app, web store, USSD) call the Maru Vend API. Every sale goes through Maru Vend's own
queue. Only the queue workers talk to BPC, at a controlled rate. No channel ever reaches BPC directly
(clause 7.6).

```
channels ──TLS+HMAC──► API ──► vend core + float ledger ──► queue ──► workers ──(rate-limited)──► VendProvider ──► BPC
                                      │                                                         ├─ XMLVend 2.1 client (BPC CONLOG) – pending BPC WSDL/XSD
                                      └─ audit chain, reports, BPC dashboard                     ├─ aggregator REST (current production flow)
                                                                                                └─ BPC simulator (test only)
```

## Stack

PHP 8.3 (Slim 4), MariaDB 10.11, Ubuntu 24.04, systemd workers, strongSwan, HAProxy/keepalived.

## Quick start (test environment)

```bash
composer install
export MV_DB_PASS=...            # DB user 'maruvend' with access to databases maruvend and maruvend_test
scripts/demo-up.sh --reset       # simulator :8099, API + dashboard :8080, 4 workers, demo data
vendor/bin/phpunit               # 24 tests
```

## Tender requirement → where it lives

| Requirement | Implementation | Demonstrate with |
|---|---|---|
| 7.1 XMLVend 2.1 only | `src/Provider/VendProvider.php` port; the XMLVend adapter is added once BPC supplies its WSDL/XSD | `bin/mv settings` (provider) |
| 7.2 / 7.3 SSL + VPN, AES-256, SHA-256/384, DH19/14, RSA 2048 | TLS verification enforced in `RestVendProvider`; `ops/strongswan/swanctl.conf`; `ops/firewall/nftables.conf` | `swanctl --list-sas`, weak peer rejected |
| 7.4 audit trail | `src/Audit/AuditLog.php`: hash chain, plus signed anchors stored outside the DB | dashboard → Audit trail → Verify; `scripts/tamper-demo.sh` |
| 7.5 protected exports | `src/Export/EncryptedExport.php`: OpenPGP AES-256 to BPC's key, signed by Maru Quick | dashboard → Reports → download |
| 7.6 queue | `src/Queue/Worker.php` (SKIP LOCKED), `src/Queue/RateLimiter.php` | `bin/mv loadtest --n=60`; simulator `/_sim/stats` shows peak rate |
| 7.8 timeouts mapped to BPC | `Settings::workerTimeout()/channelTimeout()` derive from `bpc_timeout_s` (default 120) | `bin/mv setting:request bpc_timeout_s 180` + approve; `bin/mv settings` |
| 7.9 failed responses | `VendService::processVend/processAdvice`; `ProviderResult` outcomes | `php scripts/fault-demo.php` |
| 7.11 FQDN or IP, switch without change | `bpc_endpoint`, `bpc_endpoint_backup`, `endpoint_active`, read on every request | two-person approval switches the endpoint live |
| 2.3(i) reports | `src/Reports/Reports.php`: Annexure 3 sales, point-in-time, service fee invoice, reconciliation | `bin/mv report sales|pit|invoice|recon` |
| Scope 3f BPC dashboard | `src/Dashboard/Dashboard.php`: read-only, password + TOTP | `/bpc` |

## Key design rules

- **Never vend twice.** Each sale has one `client_sale_id` (ULID), saved before the first send and reused
  on every retry and advice call. A sale whose outcome is uncertain goes to `UNKNOWN` and is only ever
  resolved with last-response. It is never re-sent.
- **Money only moves on a confirmed outcome.** Float is reserved when the sale is queued. It is settled
  when a token is issued, and released only when BPC confirms no token. Database CHECK constraints make
  a negative float impossible, and UNIQUE keys make a double settle or release impossible.
- **Unresolved exposure is capped** (`max_unknown_thebe`). New sales pause rather than drain the float
  during a BPC outage.
- **History is append-only** (`sale_events`), so point-in-time reports are exact.
- **Sensitive settings need two administrators** (`bin/mv setting:request` / `setting:approve`).

## Site visit script

1. `scripts/demo-up.sh --reset`
2. **2.3(e) Queue:** `php bin/mv loadtest --n=60`. 60 simultaneous POS, app and web sales; BPC side
   never exceeds `rate_per_s`.
3. **7.9 Faults:** `php scripts/fault-demo.php`. Rejected, processing, lost-with-token,
   lost-without-token and gateway-down cases. Exactly one credit vend per sale.
4. **2.3(f) Audit:** dashboard → Audit trail → Verify (intact). Then `scripts/tamper-demo.sh` edits a row
   directly in MariaDB → Verify shows the tampering.
5. **2.3(g) Exports:** dashboard → Reports → download. BPC opens the file with its private key; the
   signature verifies as Maru Quick.
6. **7.8 / 7.11:** admin1 requests `bpc_timeout_s=180`, admin2 approves; `bin/mv settings` shows the
   derived timeouts moved, with no restart.
7. **2.3(d) Security:** swanctl policy, firewall rules, MFA login.
8. **2.3(h) DR:** failover drill on the production pair (see `ops/`). This is infrastructure, not code.

## Not yet built

- XMLVend 2.1 SOAP adapter. Needs BPC's WSDL/XSD (NRS 009-6-10 is the public spec).
- Channel front-ends (POS screen, app, web store, USSD menus). They call this API.
- SMS token delivery and mobile-money/card payment integrations.
- Production HA/DR deployment (HAProxy, MariaDB replication with quorum witness).
