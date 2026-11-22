# Local sample hosting (XMLVend)

Runs the whole Maru Vend platform on one machine with Docker, selling prepaid electricity over
**XMLVend 2.1** to the BPC simulator. Use it to demonstrate the tender sample. **TEST / DEMO ONLY:**
every password and key in `compose.yaml` and `init.sh` is a demo value.

## Start

You need Docker Desktop (Windows or macOS) or Docker Engine with the compose plugin (Linux).
From the `maru-vend` folder:

```bash
docker compose -f ops/local/compose.yaml up -d --build
```

The first build takes a few minutes. `init` creates the schema and the demo data, then sets
`provider=xmlvend` and points the BPC endpoint at the simulator.

| What | Where |
|---|---|
| Web store | http://127.0.0.1:8081/ |
| Maru app | http://127.0.0.1:8081/app |
| Merchant POS (operator `till1`, PIN `1234`) | http://127.0.0.1:8081/pos |
| USSD emulator | http://127.0.0.1:8081/ussd-phone |
| BPC dashboard (`bpc.viewer` / `bpc-demo-pass`, TOTP secret printed by `init`) | http://127.0.0.1:8080/bpc |
| Core API | http://127.0.0.1:8080/v1 |
| BPC simulator (XMLVend SOAP at `/xmlvend`) | http://127.0.0.1:8099 |

Use demo meter `04040404040` or `94949494949`.

## Demonstrations

The fault-handling walkthrough (Annex E). It injects each fault and sells one token through the
real API and workers:

```bash
docker compose -f ops/local/compose.yaml exec api php scripts/fault-demo.php --api=http://api:8080
```

A load test with 30 simultaneous sales from POS, app and web:

```bash
docker compose -f ops/local/compose.yaml exec api php bin/mv loadtest --api=http://api:8080 --n=30
```

The crash drill for the sign-in check. Lose the BPC responses, kill every worker mid-vend, then
restart them:

```bash
curl -s -X POST 127.0.0.1:8099/_sim/mode -d '{"mode":"lost","count":4}'
```

```bash
docker compose -f ops/local/compose.yaml exec -d api php bin/mv loadtest --api=http://api:8080 --n=4
```

```bash
sleep 4; docker compose -f ops/local/compose.yaml kill worker; docker compose -f ops/local/compose.yaml start worker
```

After about 40 s, all 4 sales are `SUCCEEDED`. Each was sent to BPC once, and each lost token was
recovered with an advice before the restarted terminal sent anything new:

```bash
docker compose -f ops/local/compose.yaml exec db mariadb -umaruvend -pdevpass maruvend -e "SELECT state, COUNT(*) FROM vend_sales GROUP BY state; SELECT operation, answered, recovered IS NOT NULL AS at_signin, COUNT(*) FROM xmlvend_messages GROUP BY 1,2,3"
```

Other simulator modes (`POST /_sim/mode`): `ok`, `reject`, `processing`, `lost`, `lostfail`,
`lostindet`, `down`, `kct`.

## Stop

```bash
docker compose -f ops/local/compose.yaml down
```

To wipe the database as well, add `-v`.

## Without Docker

`scripts/demo-up.sh --reset` starts the same stack natively. It needs PHP 8.3 and MariaDB on the
machine. Then switch it to XMLVend with `php bin/mv setting:set provider xmlvend` and restart the
workers.
