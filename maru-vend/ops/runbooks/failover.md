# Failover runbook (clause 7.10, site visit 2.3(h))

**Targets:** RPO 5 minutes (in practice about 0: semi-synchronous replication), RTO 1 hour (planned
failover takes seconds; emergency failover about 1 minute).

**How it stays safe:**

- One database in the whole estate is writable. Every database starts `read_only` after a restart.
- The decision "which site is active" lives in a 3-voter quorum (primary site, DR site, witness).
  Any two voters can decide; one alone never can.
- Every DB host runs `mv-site-fence` every 5 s. If the quorum names another site, or the host cannot
  reach the quorum for 15 s, it sets its database `read_only`.
- Queue workers check before every job (`SiteGuard`). They only work when their database is writable
  and their site is the active site. A sale is recorded as SUBMITTED **before** it is sent to BPC,
  so a fenced database can never send a sale. A sale caught mid-flight is recovered with last
  response, never re-sent.

## Check state

```bash
mv-failover --status
```

## Planned failover (maintenance, the site visit demonstration)

```bash
mv-failover dr --planned
```

1. Fences the current primary (workers there stand by).
2. Waits until the DR database has every transaction (GTID).
3. Writes `dr` to the quorum (compare-and-swap).
4. Promotes DR, records `active_site=dr` in the audit trail, and repoints every other database to
   replicate from DR.

No data is lost. Vending pauses for a few seconds. HAProxy's database check (port 9200) moves
application connections to the new primary automatically.

**Site visit script:**

1. Show `mv-failover --status`.
2. Sell from POS, app and web.
3. Run `mv-failover dr --planned`.
4. Sell again.
5. Show the dashboard: the sales, the queue, and the audit entry for the failover.
6. Fail back with `mv-failover primary --planned`.

## Emergency failover (primary site lost)

Confirm the primary site is really down: no response from its DB, LB and VPN hosts, and the
data-centre NOC has confirmed. Then, from a DR or witness host:

```bash
mv-failover dr --emergency
```

It needs the quorum (DR + witness). It waits 30 s so a primary site that is merely cut off has fenced
itself, applies everything DR already received, then promotes DR.

**Afterwards:**

1. Look for sales in `UNKNOWN` / `MANUAL_REVIEW`. The workers resolve them with last response
   automatically. Check the dashboard queue.
2. Tell BPC (call tree in the BCP) that vending is running from DR.
3. **Do not** let the old primary rejoin as-is when it returns. It stays read-only (it boots
   read-only and fences itself), but it may hold transactions DR never received. Compare GTIDs with
   `mv-failover --status`. Reconcile any missing sales against BPC records, then rebuild it as a
   replica from the latest backup or a fresh `mariabackup` of DR.

## If the quorum is down (two of three voters lost)

Nothing can be promoted. This is deliberate: it is the situation where both sites could otherwise
believe they are active. Restore a voter: the witness VM can be rebuilt in minutes from the playbook
(`--limit witness`), joining with the existing cluster state. Then retry.

## Testing

- `ops/drill/local-failover-drill.sh` runs the full scenario on one machine. It covers a planned
  failover, a partition with self-fencing, and an emergency failover, and checks that no sale is
  sent to BPC twice.
- Production failover drill: quarterly, recorded in Annex F with timings.
