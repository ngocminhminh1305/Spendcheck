#!/usr/bin/env bash
# Refresh the demo user's synthetic spending so "this month" is current, then copy the database to
# the Ronin VM. The demo user always holds the six months up to the day this runs, so run it on the
# morning of a demo. Run from the repo root in Git Bash, with Docker Desktop running and the VM on:
#
#   bash scripts/refresh_demo.sh
#
# The eval user is recreated with the same fixed data, so evaluation answers do not change. Edits
# made through the website (logged entries, budgets) are replaced. The site shows no data for the
# few seconds the restore takes.
set -euo pipefail
KEY=${KEY:-$HOME/.ssh/dsa2111-g14-key.pem}
VM=${VM:-ubuntu@dsa2111-group14.nus.cloud}
DUMP="$(mktemp -d)/spendcheck-data.dump"

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Start it with \"Start Docker (DSA2111).bat\", wait until it is ready, then run this again."
  exit 1
fi
if ! ssh -q -o ConnectTimeout=10 -o BatchMode=yes -i "$KEY" "$VM" true; then
  echo "Cannot reach the VM. Start it at https://ronin.nus.cloud, wait about 3 minutes, then run this again."
  exit 1
fi

echo "1/3 Seeding the demo user locally"
docker compose up -d postgres >/dev/null 2>&1
docker compose run --rm -T chat-eval 2>&1 | grep -E "eval-user|demo-user"

echo "2/3 Copying the database to the VM"
docker compose exec -T postgres pg_dump -U postgres -d spendcheck --data-only -Fc > "$DUMP"
scp -q -i "$KEY" "$DUMP" "$VM:spendcheck/spendcheck-data.dump"

echo "3/3 Restoring on the VM"
ssh -i "$KEY" "$VM" bash -s <<'REMOTE'
set -e
cd ~/spendcheck
kubectl wait --for=condition=ready pod/postgres-0 -n spendcheck --timeout=300s >/dev/null   # after a fresh VM start
PSQL="kubectl exec -n spendcheck postgres-0 -- psql -U postgres -d spendcheck -v ON_ERROR_STOP=1 -At"
$PSQL -qc "TRUNCATE users, categories, transactions, budgets, reports.documents, reports.chunks RESTART IDENTITY CASCADE" </dev/null
kubectl exec -i -n spendcheck postgres-0 -- pg_restore -U postgres -d spendcheck --data-only --disable-triggers < spendcheck-data.dump
$PSQL -c "SELECT 'demo-user: ' || count(*) || ' transactions, latest ' || max(txn_date) FROM transactions WHERE user_id = 'demo-user'" </dev/null
$PSQL -c "SELECT 'reports: ' || count(*) || ' documents' FROM reports.documents" </dev/null
REMOTE
rm -f "$DUMP"
echo "Done. Reload the website to see the refreshed month."
