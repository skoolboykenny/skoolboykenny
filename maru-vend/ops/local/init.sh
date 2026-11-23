#!/usr/bin/env bash
# First-run setup for the local sample stack (TEST / DEMO ONLY). Safe to run again.
set -euo pipefail
php bin/mv migrate
seeded=$(php -r 'require "vendor/autoload.php"; echo MaruVend\Db::connect()->query("SELECT COUNT(*) FROM merchants")->fetchColumn();')
if [ "$seeded" = "0" ]; then
  php bin/mv seed
  MV_NEW_PASSWORD=bpc-demo-pass php bin/mv user:add bpc.viewer bpc_viewer
  MV_NEW_PASSWORD=admin1-pass php bin/mv user:add admin1 admin >/dev/null
  MV_NEW_PASSWORD=admin2-pass php bin/mv user:add admin2 admin >/dev/null
fi
# Maru Power demo login (accounts in the Maru Vend database unless MV_ACCOUNTS_DB_NAME is set).
php bin/mv portal:user demo@marupower.test "Lethabo Molefe" >/dev/null 2>&1 || true  # already exists on later runs
# Sell over XMLVend 2.1 to the simulator, with demo pacing so recovery is visible in seconds.
for kv in "provider xmlvend" "bpc_endpoint http://sim:8099" "bpc_timeout_s 4" "worker_margin_s 2" \
          "advice_first_delay_s 3" "advice_interval_s 2" "advice_window_s 20" "rate_per_s 5"; do
  php bin/mv setting:set $kv >/dev/null
done
echo "Maru Power: http://127.0.0.1:8080/power  (demo@marupower.test / maru1234)"
echo "Sample stack ready: provider=xmlvend, BPC endpoint=http://sim:8099/xmlvend"
