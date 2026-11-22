#!/usr/bin/env bash
# Failover drill on one machine (test environment): proves the failover tooling and the
# worker site guard against real MariaDB replication and a real 3-member etcd quorum.
#
#   site "primary": MariaDB :3311 + worker (MV_SITE=primary)
#   site "dr":      MariaDB :3312 (GTID replica) + worker (MV_SITE=dr)
#   quorum:         etcd x3 (:23791 primary, :23792 dr, :23793 witness)
#
# Scenario
#   1. Sell at primary; the DR worker stands by (its DB is read-only).
#   2. Planned failover to dr: no data loss; sales continue at dr; primary workers stand by.
#   3. Partition: dr loses the quorum -> mv-site-fence makes it read-only within FENCE_AFTER_S.
#   4. Emergency failover back to primary with dr unreachable; sales continue; no sale vended twice.
#
# Needs: mariadb-server 10.11, etcd, the BPC simulator on :8099 (scripts/demo-up.sh).
set -euo pipefail
cd "$(dirname "$0")/../.."
APP=$PWD
D=${DRILL_DIR:-/tmp/mv-drill}
PASS=drillpass
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

cleanup() {
  pkill -f "mv-drill-worker" 2>/dev/null || true
  pkill -f "mariadbd --defaults-file=$D/" 2>/dev/null || true; sleep 2
  pkill -f "etcd --name mvq" 2>/dev/null || true
}
trap cleanup EXIT
cleanup; sleep 1; rm -rf "$D"; mkdir -p "$D"

step "Start 3-member quorum (two sites + witness)"
for i in 1 2 3; do
  etcd --name mvq$i --data-dir "$D/etcd$i" \
    --listen-client-urls http://127.0.0.1:2379$i --advertise-client-urls http://127.0.0.1:2379$i \
    --listen-peer-urls http://127.0.0.1:2380$i --initial-advertise-peer-urls http://127.0.0.1:2380$i \
    --initial-cluster mvq1=http://127.0.0.1:23801,mvq2=http://127.0.0.1:23802,mvq3=http://127.0.0.1:23803 \
    --initial-cluster-state new >"$D/etcd$i.log" 2>&1 &
done
sleep 3

step "Start two MariaDB servers with GTID binlogs, read_only=ON at boot"
for n in 1 2; do
  port=331$n
  mkdir -p "$D/db$n"
  cat >"$D/db$n.cnf" <<EOF
[mysqld]
datadir=$D/db$n
socket=$D/db$n.sock
port=$port
bind-address=127.0.0.1
server_id=$n
log_bin=$D/db$n/binlog
log_slave_updates=ON
binlog_format=ROW
gtid_strict_mode=ON
read_only=ON
skip-name-resolve
EOF
  mariadb-install-db --defaults-file="$D/db$n.cnf" --user=root --auth-root-authentication-method=normal >/dev/null 2>&1
  mariadbd --defaults-file="$D/db$n.cnf" --user=root >"$D/db$n.log" 2>&1 &
done
for n in 1 2; do for i in $(seq 1 30); do mariadb -S "$D/db$n.sock" -uroot -e "select 1" >/dev/null 2>&1 && break; sleep 0.5; done; done

for n in 1 2; do
  mariadb -S "$D/db$n.sock" -uroot -e "
    SET sql_log_bin=0;
    ALTER USER root@localhost IDENTIFIED BY '$PASS';
    CREATE USER IF NOT EXISTS root@'127.0.0.1'; ALTER USER root@'127.0.0.1' IDENTIFIED BY '$PASS'; GRANT ALL ON *.* TO root@'127.0.0.1' WITH GRANT OPTION;"
done
# Accounts are created on db1 only and reach db2 by replication.
mariadb -h127.0.0.1 -P3311 -uroot -p$PASS -e "
  SET GLOBAL read_only=0;
  CREATE USER repl@'127.0.0.1' IDENTIFIED BY '$PASS'; GRANT REPLICATION SLAVE ON *.* TO repl@'127.0.0.1';
  CREATE DATABASE maruvend; CREATE USER maruvend@'127.0.0.1' IDENTIFIED BY '$PASS'; GRANT ALL ON maruvend.* TO maruvend@'127.0.0.1';"
mariadb -h127.0.0.1 -P3312 -uroot -p$PASS -e "
  CHANGE MASTER TO MASTER_HOST='127.0.0.1', MASTER_PORT=3311, MASTER_USER='repl', MASTER_PASSWORD='$PASS', MASTER_USE_GTID=slave_pos; START SLAVE;"

export MV_OPS_ENV=/dev/null MV_SITES="primary dr" SITE_DB_primary="127.0.0.1:3311" SITE_DB_dr="127.0.0.1:3312"
export ETCD_ENDPOINTS="http://127.0.0.1:23791,http://127.0.0.1:23792,http://127.0.0.1:23793"
export DB_ADMIN_USER=root DB_ADMIN_PASS=$PASS REPL_USER=repl REPL_PASS=$PASS REPL_SSL=0 MV_APP_DIR=$APP
export FENCE_AFTER_S=4 FENCE_GRACE_S=8
export MV_DB_HOST=127.0.0.1 MV_DB_USER=maruvend MV_DB_PASS=$PASS MV_DB_NAME=maruvend
export MV_ANCHOR_DIR=$D/anchors MV_ANCHOR_KEY_FILE=$D/anchor.key

MV_DB_PORT=3311 php bin/mv migrate >/dev/null
MV_DB_PORT=3311 php bin/mv seed >/dev/null
for kv in "bpc_timeout_s 4" "worker_margin_s 2" "advice_first_delay_s 2" "advice_interval_s 2" "rate_per_s 10" "active_site primary"; do
  MV_DB_PORT=3311 php bin/mv setting:set $kv >/dev/null
done
ETCDCTL_API=3 etcdctl --endpoints=$ETCD_ENDPOINTS put /maruvend/active_site primary >/dev/null
gtid=$(mariadb -h127.0.0.1 -P3311 -uroot -p$PASS -N -e "SELECT @@gtid_binlog_pos")
[ "$(mariadb -h127.0.0.1 -P3312 -uroot -p$PASS -N -e "SELECT MASTER_GTID_WAIT('$gtid', 30)")" = "0" ] || { echo "replica not in sync"; exit 1; }
ops/scripts/mv-failover --status

worker() { (exec -a mv-drill-worker env MV_SITE=$1 MV_DB_PORT=$2 php bin/mv worker --id=$1 >>"$D/worker-$1.log" 2>&1) & }
worker primary 3311
worker dr 3312

sell() { # sell N sales on the DB at port $1, print outcomes
  MV_DB_PORT=$1 php -r '
    require "vendor/autoload.php";
    $app = MaruVend\App::boot();
    $ch = $app->pdo->query("SELECT * FROM channels WHERE type=\"POS\"")->fetch();
    $ids = [];
    for ($i = 0; $i < (int) $argv[1]; $i++) {
      $s = $app->vend()->quote($ch, "04040404040", 2000 + $i * 100, "drill-" . bin2hex(random_bytes(4)));
      $app->vend()->accept($ch, (int) $s["id"]);
      $ids[] = (int) $s["id"];
    }
    $t = time();
    do { usleep(300000);
      $left = $app->pdo->query("SELECT COUNT(*) FROM vend_sales WHERE id IN (" . implode(",", $ids) . ") AND state NOT IN (\"SUCCEEDED\",\"FAILED\")")->fetchColumn();
    } while ($left > 0 && time() - $t < 60);
    echo "  " . count($ids) . " sales: " . json_encode($app->pdo->query("SELECT state, COUNT(*) FROM vend_sales WHERE id IN (" . implode(",", $ids) . ") GROUP BY state")->fetchAll(PDO::FETCH_KEY_PAIR)) . "\n";
  ' "$2"
}
who_vended() { MV_DB_PORT=$1 php -r 'require "vendor/autoload.php"; $a=MaruVend\App::boot();
  echo "  worker log of last 5 sales: " . json_encode($a->pdo->query("SELECT q.locked_by, COUNT(*) FROM queue_jobs q GROUP BY q.locked_by")->fetchAll(PDO::FETCH_KEY_PAIR)) . "\n";'; }

step "1. Normal operation: sell 5 at primary"
sell 3311 5
grep -h "standing by" "$D/worker-dr.log" | head -1 | sed 's/^/  dr worker: /' || true

step "2. Planned failover to dr"
ops/scripts/mv-failover dr --planned
sleep 2
sell 3312 5
grep -h "standing by" "$D/worker-primary.log" | tail -1 | sed 's/^/  primary worker: /' || true

step "3. Partition: dr cut off from the quorum (its etcd member and the witness unreachable)"
ETCD_ENDPOINTS="http://127.0.0.1:23792" bash -c '
  pkill -f "^etcd --name mvq1 "; pkill -f "^etcd --name mvq3 "; sleep 1
  for i in 1 2 3 4 5 6 7; do MV_SITE=dr LOCAL_DB=127.0.0.1:3312 FENCE_STATE='"$D"'/fence.state ops/scripts/mv-site-fence; sleep 1; done'
echo "  dr database read_only = $(mariadb -h127.0.0.1 -P3312 -uroot -p$PASS -N -e 'SELECT @@read_only')  (1 = fenced, cannot vend)"

step "4. Emergency failover back to primary (dr unreachable)"
mariadb-admin -h127.0.0.1 -P3312 -uroot -p$PASS shutdown
for i in 1 3; do
  etcd --name mvq$i --data-dir "$D/etcd$i" \
    --listen-client-urls http://127.0.0.1:2379$i --advertise-client-urls http://127.0.0.1:2379$i \
    --listen-peer-urls http://127.0.0.1:2380$i --initial-advertise-peer-urls http://127.0.0.1:2380$i \
    --initial-cluster mvq1=http://127.0.0.1:23801,mvq2=http://127.0.0.1:23802,mvq3=http://127.0.0.1:23803 \
    --initial-cluster-state existing >>"$D/etcd$i.log" 2>&1 &
done
sleep 3
pkill -f "^etcd --name mvq2 "   # dr's quorum member is gone with the site; witness + primary still form a majority
sleep 1
ops/scripts/mv-failover primary --emergency
sleep 2
sell 3311 5

step "Result"
MV_DB_PORT=3311 php -r 'require "vendor/autoload.php"; $a=MaruVend\App::boot();
  $s=$a->pdo->query("SELECT state, COUNT(*) FROM vend_sales GROUP BY state")->fetchAll(PDO::FETCH_KEY_PAIR);
  $dup=$a->pdo->query("SELECT COUNT(*) FROM (SELECT sale_id FROM vend_messages WHERE operation=\"creditvend\" AND direction=\"req\" GROUP BY sale_id HAVING COUNT(*)>1) x")->fetchColumn();
  echo "  Sales on the surviving primary: " . json_encode($s) . "\n  Sales sent to BPC more than once: $dup\n";
  echo "  active_site setting: " . $a->settings->get("active_site") . "\n";
  $v=$a->audit->verify(); echo "  Audit chain: " . ($v["ok"] ? "intact" : "BROKEN") . " (" . $v["rows"] . " rows)\n";'
