#!/usr/bin/env bash
set -Eeuo pipefail

IMS_PATH=${1:?IMS_PATH is required}
IMS_PATH=$(readlink -f -- "$IMS_PATH")
cd "$IMS_PATH"

test "$IMS_PATH" = "/home/ubuntu/ims_system"
test "$(git branch --show-current)" = "main"
test -z "$(git status --porcelain)"
test -s instance/ipm.db

exec 9>"$IMS_PATH/instance/.production-maintenance.lock"
flock -n 9 || { echo 'OBSOLETE_CLEANUP|SKIPPED|reason=maintenance_running'; exit 1; }

processing=$(venv/bin/python - <<'PY'
import sqlite3

connection = sqlite3.connect('instance/ipm.db', timeout=30)
try:
    connection.execute('PRAGMA busy_timeout=30000')
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ims_import_jobs'"
    ).fetchone()
    count = 0 if not exists else int(connection.execute(
        "SELECT COUNT(*) FROM ims_import_jobs WHERE status IN ('QUEUED', 'PROCESSING')"
    ).fetchone()[0])
finally:
    connection.close()
print(count)
PY
)
echo "IMS_ACTIVE_JOBS|$processing"
test "$processing" = "0"

mapfile -t retained_backups < <(find instance/backups -maxdepth 1 -type f -name 'ipm-predeploy-*.db' -printf '%p\n')
test "${#retained_backups[@]}" -eq 1
retained_backup=${retained_backups[0]}
test -s "$retained_backup"

venv/bin/python - "$retained_backup" <<'PY'
import sqlite3
import sys

for database in ('instance/ipm.db', sys.argv[1]):
    connection = sqlite3.connect(f'file:{database}?mode=ro', uri=True, timeout=30)
    try:
        connection.execute('PRAGMA busy_timeout=30000')
        result = str(connection.execute('PRAGMA quick_check(1)').fetchone()[0])
    finally:
        connection.close()
    print(f'SQLITE_PRE_CLEANUP|database={database}|quick_check={result}')
    if result.lower() != 'ok':
        raise SystemExit(f'Integrity validation failed for {database}: {result}')
PY

db_identity_before=$(stat -Lc '%d:%i:%s' instance/ipm.db)
free_before=$(df -B1 --output=avail / | tail -n 1 | tr -d ' ')
deleted_bytes=0
deleted_count=0

delete_file() {
  local path=$1
  local resolved expected size
  if [ ! -e "$path" ]; then
    echo "OBSOLETE_FILE|SKIP_MISSING|$path"
    return 0
  fi
  test -f "$path"
  test ! -L "$path"
  resolved=$(readlink -f -- "$path")
  expected=$(readlink -m -- "$path")
  test "$resolved" = "$expected"
  size=$(stat -Lc '%s' "$path")
  rm -f -- "$path"
  deleted_bytes=$((deleted_bytes + size))
  deleted_count=$((deleted_count + 1))
  echo "OBSOLETE_FILE|DELETED|bytes=$size|$path"
}

delete_tree() {
  local path=$1
  local resolved expected size files
  if [ ! -e "$path" ]; then
    echo "OBSOLETE_TREE|SKIP_MISSING|$path"
    return 0
  fi
  test -d "$path"
  test ! -L "$path"
  resolved=$(readlink -f -- "$path")
  expected=$(readlink -m -- "$path")
  test "$resolved" = "$expected"
  case "$resolved" in
    "$IMS_PATH/instance/test-baselines"|\
    "$IMS_PATH/instance/backups/atomic-week16-cutover-20260908-053534") ;;
    *) echo "Refusing unexpected cleanup tree: $resolved" >&2; exit 1 ;;
  esac
  test -z "$(find "$path" -xdev -type l -print -quit)"
  size=$(du -sx -B1 "$path" | awk '{print $1}')
  files=$(find "$path" -xdev -type f | wc -l)
  rm -rf -- "$resolved"
  deleted_bytes=$((deleted_bytes + size))
  deleted_count=$((deleted_count + files))
  echo "OBSOLETE_TREE|DELETED|bytes=$size|files=$files|$path"
}

# Superseded isolated recovery/test copies. The active database, the one
# verified predeploy set, the reusable rollback proof base, archives and
# application snapshots are intentionally not members of this allowlist.
delete_tree "$IMS_PATH/instance/test-baselines"
delete_tree "$IMS_PATH/instance/backups/atomic-week16-cutover-20260908-053534"
delete_file "$IMS_PATH/backups/pre_week14_compact_tts_actual_repair_20260831_212357.sqlite"
delete_file "$IMS_PATH/backups/pre_march_stage2_apply_20260901_082416.sqlite"
delete_file "/tmp/ipm-before-week8-balance-unit-repair-20260829T062526Z.db"
delete_file "/tmp/ipm-before-week8-balance-unit-repair-20260829T061516Z.db"
delete_file "/tmp/ipm-before-week8-summary-repair-20260828T164543Z.db"
delete_file "/tmp/ims-acceptance-20260827-081649.db"
delete_file "/tmp/ims-acceptance-20260827-081649.db-wal"

db_identity_after=$(stat -Lc '%d:%i:%s' instance/ipm.db)
test "$db_identity_after" = "$db_identity_before"

venv/bin/python - <<'PY'
import sqlite3

connection = sqlite3.connect('file:instance/ipm.db?mode=ro', uri=True, timeout=30)
try:
    connection.execute('PRAGMA busy_timeout=30000')
    mode = str(connection.execute('PRAGMA journal_mode').fetchone()[0])
    result = str(connection.execute('PRAGMA quick_check(1)').fetchone()[0])
finally:
    connection.close()
print(f'SQLITE_POST_CLEANUP|journal_mode={mode}|quick_check={result}')
if mode.lower() != 'wal' or result.lower() != 'ok':
    raise SystemExit('Live database post-cleanup validation failed')
PY

test -s "$retained_backup"
test -s "$IMS_PATH/instance/rollback-module-proof-base-upload-31.db"
test -d "$IMS_PATH/uploads/ims_archive"

web_state=$(sudo systemctl is-active ims-performance-manager.service)
worker_state=$(sudo systemctl is-active ims-import-worker.service)
test "$web_state" = "active"
test "$worker_state" = "active"
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8000/login >/dev/null

free_after=$(df -B1 --output=avail / | tail -n 1 | tr -d ' ')
echo "STORAGE_CLEANUP|deleted_files=$deleted_count|deleted_bytes=$deleted_bytes|free_before=$free_before|free_after=$free_after"
echo "RETAINED_ACTIVE_DB|$IMS_PATH/instance/ipm.db"
echo "RETAINED_BACKUP|$retained_backup"
echo "RETAINED_TEST_BASE|$IMS_PATH/instance/rollback-module-proof-base-upload-31.db"
echo "SERVICE_HEALTH|web=$web_state|worker=$worker_state|http=PASS"
echo 'OBSOLETE_CLEANUP_RESULT|PASS'
