# Shared helpers for Maru Vend operations scripts. Sourced, not executed.
# Configuration comes from /etc/maruvend/ops.env (or MV_OPS_ENV), for example:
#
#   MV_SITE=primary                         # site this host belongs to
#   MV_SITES="primary dr"
#   SITE_DB_primary="10.10.1.21:3306 10.10.1.22:3306"   # first host = preferred primary at that site
#   SITE_DB_dr="10.20.1.21:3306 10.20.1.22:3306"
#   ETCD_ENDPOINTS="https://10.10.1.30:2379,https://10.20.1.30:2379,https://10.30.1.30:2379"  # 2 sites + witness
#   DB_ADMIN_USER=mvops  DB_ADMIN_PASS=...   # failover administrator (or use ~/.my.cnf)
#   REPL_USER=repl       REPL_PASS=...
#   MV_APP_DIR=/opt/maruvend/current
#   FENCE_AFTER_S=15  FENCE_GRACE_S=30

set -euo pipefail
: "${MV_OPS_ENV:=/etc/maruvend/ops.env}"
# shellcheck disable=SC1090
[ -f "$MV_OPS_ENV" ] && . "$MV_OPS_ENV"
: "${MV_SITES:=primary dr}"
: "${FENCE_AFTER_S:=15}"
: "${FENCE_GRACE_S:=30}"
: "${ETCD_KEY:=/maruvend/active_site}"

log() { printf '%s [%s] %s\n' "$(date '+%F %T')" "${0##*/}" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

site_hosts() { local v="SITE_DB_$1"; echo "${!v:-}"; }

# sql HOST:PORT "statement"  -> tab-separated output, no headers
sql() {
  local hp=$1; shift
  mariadb --connect-timeout=3 -h "${hp%:*}" -P "${hp#*:}" -u "${DB_ADMIN_USER:-root}" ${DB_ADMIN_PASS:+-p"$DB_ADMIN_PASS"} -N -B -e "$*"
}
# sqlv HOST:PORT "SHOW ... \\G" -> "Name: value" lines (vertical output keeps field names)
sqlv() {
  local hp=$1; shift
  mariadb --connect-timeout=3 -h "${hp%:*}" -P "${hp#*:}" -u "${DB_ADMIN_USER:-root}" ${DB_ADMIN_PASS:+-p"$DB_ADMIN_PASS"} -e "$*"
}
db_up() { sql "$1" "SELECT 1" >/dev/null 2>&1; }
db_writable() { [ "$(sql "$1" "SELECT @@global.read_only" 2>/dev/null)" = "0" ]; }
# MariaDB 10.11: read_only blocks every account without READ_ONLY ADMIN (the application user has
# none), while replication keeps applying. All servers also start with read_only=ON (my.cnf), so a
# database that restarts is fenced until mv-failover promotes it.
fence_db() { sql "$1" "SET GLOBAL read_only = 1"; }

# Wait (up to $2 s) until a replica has applied everything it has received.
wait_relay_applied() {
  local hp=$1 deadline=$(( $(date +%s) + ${2:-30} ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    local st; st=$(sqlv "$hp" "SHOW SLAVE STATUS\G" 2>/dev/null || true)
    [ -z "$st" ] && return 0
    local rd ex; rd=$(awk '/^ *Read_Master_Log_Pos:/{print $2}' <<<"$st"); ex=$(awk '/^ *Exec_Master_Log_Pos:/{print $2}' <<<"$st")
    local rf ef; rf=$(awk '/^ *Master_Log_File:/{print $2; exit}' <<<"$st"); ef=$(awk '/^ *Relay_Master_Log_File:/{print $2}' <<<"$st")
    [ "$rd" = "$ex" ] && [ "$rf" = "$ef" ] && return 0
    sleep 1
  done
  return 1
}

etcd() { ETCDCTL_API=3 etcdctl --endpoints="$ETCD_ENDPOINTS" --command-timeout=3s ${ETCD_CACERT:+--cacert="$ETCD_CACERT"} ${ETCD_CERT:+--cert="$ETCD_CERT" --key="$ETCD_KEY_FILE"} "$@"; }
# Linearizable read: succeeds only while a majority of the three voters is reachable.
quorum_active_site() { etcd get "$ETCD_KEY" --consistency=l --print-value-only; }
# Compare-and-swap so two operators (or two partitions) can never both win.
# Prints SUCCESS or FAILURE. etcdctl txn input: compares, blank line, success ops, blank line,
# failure ops (none here), blank line.
quorum_cas() {
  local old=$1 new=$2 cmp
  if [ -z "$old" ]; then cmp="create(\"$ETCD_KEY\") = \"0\""; else cmp="value(\"$ETCD_KEY\") = \"$old\""; fi
  printf '%s\n\nput %s %s\n\n\n' "$cmp" "$ETCD_KEY" "$new" | etcd txn | head -1
}
