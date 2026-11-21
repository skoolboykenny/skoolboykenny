#!/usr/bin/env bash
# Site visit 2.3(f): show that a direct database edit to the audit trail is detected.
# Usage: MV_DB_PASS=... scripts/tamper-demo.sh
set -euo pipefail
cd "$(dirname "$0")/.."
: "${MV_DB_PASS:?set MV_DB_PASS}"

echo "1. Sign the current audit chain head (done hourly in production):"
php bin/mv audit:anchor
echo
echo "2. Verify before tampering:"
php bin/mv audit:verify || true
echo
ROW=$(mariadb -N -u maruvend -p"$MV_DB_PASS" maruvend -e "SELECT id FROM audit_log WHERE action='sale.succeeded' ORDER BY id LIMIT 1")
echo "3. An administrator changes audit row $ROW directly in the database (SUCCEEDED -> FAILED):"
mariadb -u maruvend -p"$MV_DB_PASS" maruvend -e "UPDATE audit_log SET new_value='FAILED' WHERE id=$ROW"
echo
echo "4. Verify again:"
php bin/mv audit:verify || echo ">>> Tampering detected (exit code 2)."
