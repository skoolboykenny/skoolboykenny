#!/usr/bin/env bash
# Crash drill for the local sample stack (TEST / DEMO ONLY).
# Sells N sales, loses BPC's responses for some of them, kills every worker while credit vends are
# in flight, restarts them after a pause, and reports how long recovery took and whether any sale
# was lost, double-vended or left holding float.
# Usage: ops/local/crash-drill.sh [sales=40] [lost=6] [pause_s=10]
set -euo pipefail
cd "$(dirname "$0")/../.."
N="${1:-40}"; LOST="${2:-6}"; PAUSE="${3:-10}"
C=(docker compose -f ops/local/compose.yaml)
q() { "${C[@]}" exec -T db mariadb -umaruvend -pdevpass maruvend -N -e "$1"; }

start=$(q "SELECT COALESCE(MAX(id),0) FROM vend_sales")
curl -s -X POST 127.0.0.1:8099/_sim/mode -d "{\"mode\":\"lost\",\"count\":$LOST}" > /dev/null
"${C[@]}" exec -T api php bin/mv loadtest --api=http://api:8080 --n="$N" > /dev/null 2>&1 &

inflight=0
for _ in $(seq 1 120); do
  inflight=$(q "SELECT COUNT(*) FROM vend_sales WHERE id > $start AND state = 'SUBMITTED'")
  [ "$inflight" -ge 2 ] && break
  sleep 0.5
done
"${C[@]}" kill worker > /dev/null 2>&1
echo "Killed all workers with $inflight credit vend(s) in flight; restarting in ${PAUSE}s"
sleep "$PAUSE"
restart=$(date +%s.%N)
"${C[@]}" start worker > /dev/null 2>&1

for _ in $(seq 1 240); do
  total=$(q "SELECT COUNT(*) FROM vend_sales WHERE id > $start")
  open=$(q "SELECT COUNT(*) FROM vend_sales WHERE id > $start AND state NOT IN ('SUCCEEDED','FAILED')")
  [ "$total" -ge "$N" ] && [ "$open" = 0 ] && break
  sleep 0.5
done
done_at=$(date +%s.%N)
wait

echo "Restart to all $N sales resolved: $(python3 -c "print(round($done_at - $restart, 1))") s"
echo "Outcomes:"; q "SELECT state, COUNT(*) FROM vend_sales WHERE id > $start GROUP BY state"
echo "Most answered credit vends for one sale (must be 1): $(q "SELECT COALESCE(MAX(c),0) FROM (SELECT COUNT(*) c FROM xmlvend_messages m JOIN vend_sales s ON m.client_sale_id = s.client_sale_id WHERE s.id > $start AND m.operation = 'creditvend' AND m.answered = 1 GROUP BY s.id) x")"
echo "Tokens recovered at sign-in: $(q "SELECT COUNT(*) FROM xmlvend_messages m JOIN vend_sales s ON m.client_sale_id = s.client_sale_id WHERE s.id > $start AND m.recovered IS NOT NULL")"
echo "Restart to resolved, for the sales hit by the crash (s): $(q "SELECT ROUND(TIMESTAMPDIFF(MICROSECOND, FROM_UNIXTIME($restart), s.resolved_at) / 1e6, 1) FROM vend_sales s WHERE s.id > $start AND EXISTS (SELECT 1 FROM xmlvend_messages m WHERE m.client_sale_id = s.client_sale_id AND m.recovered IS NOT NULL)" | tr '\n' ' ')"
echo "Float still reserved (thebe, must be 0): $(q "SELECT SUM(reserved) FROM float_position")"
echo "Worker log lines:"; "${C[@]}" logs worker 2>&1 | grep -E "released|sign-in" | tail -8 || true
