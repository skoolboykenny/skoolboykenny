# Production build runbook

Builds the Maru Vend production estate from bare Ubuntu 24.04 servers using `ops/ansible`.

## What you need first (lead times!)

| Item | From | Needed for |
|---|---|---|
| Rack space or VMs at **two Botswana data centres** (primary + DR), dual power, two carriers each | BoFiNet, Mascom, Orange DC (quotes) | Everything; site visit 2.3(h) |
| A small **witness** VM at a third location (can be a third DC or a cloud VM holding **no customer data**) | Any provider | Quorum: lets one site take over safely when the other is cut off |
| 4 x app, 4 x DB, 4 x LB, 4 x VPN servers (2 of each per site), plus the witness | Hardware/VM order | |
| Public IPs + DNS for `api.`, `bpc.` (dashboard) and `electricity.` (store) | Carrier / registrar | |
| TLS certificates for those names | CA | HAProxy |
| IPsec peer details, BPC test endpoint, BPC's timeout value, BPC's export public key | BPC (after award) | VPN, certification, exports |
| Aggregator / XMLVend credentials, SMS provider account, payment provider accounts | Providers | Live sales |

Every data disk is LUKS-encrypted when the server is installed (the playbook warns if not).

## Build order

```bash
cd ops/ansible
cp inventory/production.yml inventory/production.yml   # fill in real addresses (replace every <...>)
ansible-vault create group_vars/vault.yml              # secrets: see list at top of group_vars/all.yml
ansible-playbook site.yml --limit witness --ask-vault-pass
ansible-playbook site.yml --limit site_primary --ask-vault-pass
ansible-playbook site.yml --limit site_dr --ask-vault-pass
```

Then, once:

1. **Replication.** On each DB except `mv-p-db1`:
   `CHANGE MASTER TO MASTER_HOST='<mv-p-db1>', MASTER_USER='repl', MASTER_PASSWORD=..., MASTER_USE_GTID=slave_pos, MASTER_SSL=1; START SLAVE;`
2. **Promote the first primary.** On `mv-p-db1`: `SET GLOBAL read_only=0;`, then
   `ETCDCTL_API=3 etcdctl --endpoints=... put /maruvend/active_site primary`.
3. **Schema and data.** From an app server: `php bin/mv migrate`, then create users (`bin/mv user:add`),
   merchants and channels, and record the first BPC deposit.
4. **Check.** Run `mv-failover --status` on any DB host. Exactly one database should be WRITABLE and
   all replicas should show `sql_running=Yes`.
5. **First drill.** Run the planned failover to `dr` and back (see failover.md) before going live.

Every config change after this point goes through Git and the playbook, never by hand.
