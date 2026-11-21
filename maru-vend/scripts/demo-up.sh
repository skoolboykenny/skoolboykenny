#!/usr/bin/env bash
# Start a complete Maru Vend demo stack on one machine (test environment only):
# BPC simulator :8099, Maru Vend API + BPC dashboard :8080, 4 queue workers.
# Usage: MV_DB_PASS=... scripts/demo-up.sh [--reset]
set -euo pipefail
cd "$(dirname "$0")/.."
export MV_DB_PASS="${MV_DB_PASS:?set MV_DB_PASS}"
[ -f /tmp/mv-gpg.env ] && export $(cat /tmp/mv-gpg.env)

pkill -f "bin/mv worker" 2>/dev/null || true
pkill -f "php -S 127.0.0.1:80" 2>/dev/null || true
sleep 1

if [ "${1:-}" = "--reset" ]; then
  mariadb -u maruvend -p"$MV_DB_PASS" -e "DROP DATABASE IF EXISTS maruvend; CREATE DATABASE maruvend;"
  rm -f /tmp/maruvend-sim.sqlite* "${MV_ANCHOR_DIR:-/tmp/maruvend-anchors}/anchors.jsonl"
  php bin/mv migrate
  php bin/mv seed
  # Demo pacing: short timeouts so failure recovery is visible in seconds, not minutes.
  for kv in "bpc_timeout_s 4" "worker_margin_s 2" "advice_first_delay_s 3" "advice_interval_s 2" "advice_window_s 20" "rate_per_s 5"; do
    php bin/mv setting:set $kv >/dev/null
  done
  MV_NEW_PASSWORD=bpc-demo-pass php bin/mv user:add bpc.viewer bpc_viewer
  MV_NEW_PASSWORD=admin1-pass php bin/mv user:add admin1 admin >/dev/null
  MV_NEW_PASSWORD=admin2-pass php bin/mv user:add admin2 admin >/dev/null
fi

PHP_CLI_SERVER_WORKERS=16 nohup php -S 127.0.0.1:8099 simulator/index.php >/tmp/sim.log 2>&1 &
PHP_CLI_SERVER_WORKERS=16 nohup php -S 127.0.0.1:8080 -t public public/index.php >/tmp/api.log 2>&1 &
for w in 1 2 3 4; do nohup php bin/mv worker --id=w$w >/tmp/worker$w.log 2>&1 & done
sleep 1
echo "Simulator http://127.0.0.1:8099  API http://127.0.0.1:8080/v1  Dashboard http://127.0.0.1:8080/bpc"
