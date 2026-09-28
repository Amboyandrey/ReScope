#!/usr/bin/env bash
# Restores the newest S3 dump into a scratch database beside the live one and compares row counts.
#   restore-drill.sh staging|prod <backups-bucket>
# Needs AWS credentials that can read the bucket, and kubectl pointed at the cluster.
set -euo pipefail

env="${1:?usage: restore-drill.sh staging|prod <bucket>}"
bucket="${2:?usage: restore-drill.sh staging|prod <bucket>}"
ns="rescope-$env"
pod="rescope-postgres-0"
scratch="restore_drill"
tables=(tenants memberships companies offerings competencies embeddings audit_logs)

start=$(date +%s)
latest=$(aws s3 ls "s3://$bucket/$ns/" | sort | tail -n1 | awk '{print $4}')
[[ -n "$latest" ]] || { echo "no dumps under s3://$bucket/$ns/" >&2; exit 1; }
echo "restoring $latest"

aws s3 cp "s3://$bucket/$ns/$latest" - \
  | kubectl exec -i -n "$ns" "$pod" -- sh -c 'cat > /tmp/drill.dump'

psql() { kubectl exec -n "$ns" "$pod" -- psql -U rescope -tAq "$@"; }
psql -d rescope -c "DROP DATABASE IF EXISTS $scratch" -c "CREATE DATABASE $scratch"
kubectl exec -n "$ns" "$pod" -- pg_restore -U rescope --no-owner --exit-on-error -d "$scratch" /tmp/drill.dump

printf '%-14s %10s %10s\n' table live restored
for t in "${tables[@]}"; do
  printf '%-14s %10s %10s\n' "$t" "$(psql -d rescope -c "SELECT count(*) FROM $t")" "$(psql -d "$scratch" -c "SELECT count(*) FROM $t")"
done

psql -d rescope -c "DROP DATABASE $scratch"
kubectl exec -n "$ns" "$pod" -- rm -f /tmp/drill.dump
echo "restore drill finished in $(( $(date +%s) - start ))s (live rows may exceed restored rows written since the dump)"
