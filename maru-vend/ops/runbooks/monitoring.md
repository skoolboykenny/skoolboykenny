# Monitoring and alerts (Zabbix)

| Item | Alert when | Meaning / first action |
|---|---|---|
| `mv.db.writable` (sum over all DB hosts) | ≠ 1 | 0: nobody can vend, so run `mv-failover --status`. 2: split brain, so fence one immediately |
| `mv.db.lag` | > 30 s for 2 min | Replica falling behind; check links |
| `mv.db.sql_running` | ≠ Yes | Replication stopped; read `SHOW SLAVE STATUS` |
| `mv.queue.depth` | > 50 for 2 min | BPC slow or workers down |
| `mv.unresolved.thebe` | > 50% of `max_unknown_thebe` | BPC not confirming sales; vending will pause at 100% |
| `mv.manual_review.old` | > 0 | Sale unresolved over 2 h; reconcile with BPC (clause 7.9) |
| `mv.float.available` | < 20% of last deposit | Ask Finance to deposit with BPC |
| `mv.failed.15m` | sudden rise | BPC-side fault; check the fault codes on the dashboard |
| `mv.sms.failed` | > 0 | SMS provider problem; failover URL used? |
| `mv.audit.verify` | ≠ 0 | **Audit chain broken: security incident.** Preserve evidence |
| `mv.vpn.sas` | 0 on active site | Tunnel to BPC down; check the VPN pair |

Alerts go to the on-call engineer by SMS and email, and to the 24-hour contact centre.
