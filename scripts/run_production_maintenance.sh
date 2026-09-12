#!/usr/bin/env bash
set -Eeuo pipefail

IMS_PATH=${1:?IMS_PATH is required}
JOB_DIR=${2:?JOB_DIR is required}

mkdir -p "$JOB_DIR"
STATUS_FILE="$JOB_DIR/status"
EVIDENCE_FILE="$JOB_DIR/evidence.log"
LOCK_FILE="$IMS_PATH/instance/.production-maintenance.lock"

: > "$EVIDENCE_FILE"
printf 'RUNNING\n' > "$STATUS_FILE"

finish() {
  rc=$?
  if [ "$rc" -eq 0 ]; then
    printf 'PASS\n' > "$STATUS_FILE"
    printf 'MAINTENANCE_RESULT|PASS\n' >> "$EVIDENCE_FILE"
  else
    printf 'FAIL|exit_code=%s\n' "$rc" > "$STATUS_FILE"
    printf 'MAINTENANCE_RESULT|FAIL|exit_code=%s\n' "$rc" >> "$EVIDENCE_FILE"
  fi
}
trap finish EXIT

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  printf 'MAINTENANCE_SKIPPED|reason=already_running\n' >> "$EVIDENCE_FILE"
  exit 0
fi

cd "$IMS_PATH"
printf 'LIVE_COMMIT|%s\n' "$(git rev-parse HEAD)" >> "$EVIDENCE_FILE"
test "$(git branch --show-current)" = "main"
test -z "$(git status --porcelain)"

processing=$(venv/bin/python - <<'PY'
import sqlite3
from pathlib import Path

database = Path('instance/ipm.db')
if not database.exists():
    print(0)
    raise SystemExit(0)
connection = sqlite3.connect(database, timeout=30)
try:
    connection.execute('PRAGMA busy_timeout=30000')
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ims_import_jobs'"
    ).fetchone()
    value = 0 if not exists else int(connection.execute(
        "SELECT COUNT(*) FROM ims_import_jobs WHERE status IN ('QUEUED','PROCESSING')"
    ).fetchone()[0])
finally:
    connection.close()
print(value)
PY
)
printf 'IMS_PROCESSING|%s\n' "$processing" >> "$EVIDENCE_FILE"
if [ "$processing" != "0" ]; then
  printf 'MAINTENANCE_SKIPPED|reason=active_import|processing=%s\n' "$processing" >> "$EVIDENCE_FILE"
  exit 0
fi

# One-time, idempotent Week 32 repair.  This rides the long-established
# production-maintenance workflow because that workflow already has the
# production environment, SSH credentials, detached execution and polling.
# Once 2026/08 targets exist this block is a permanent no-op.
week32_recovery=$(venv/bin/python - <<'PY'
from app import create_app
from app.models import IMSUpload, Target
from config import Config
app = create_app(Config)
with app.app_context():
    latest = IMSUpload.query.filter_by(status=IMSUpload.STATUS_COMPLETED).order_by(
        IMSUpload.year.desc(), IMSUpload.month.desc(), IMSUpload.week_number.desc(),
        IMSUpload.completed_at.desc(), IMSUpload.id.desc(),
    ).first()
    targets = Target.query.filter_by(year=2026, month=8).count()
    eligible = bool(latest and int(latest.year) == 2026 and int(latest.month) == 8 and int(latest.week_number) == 32 and targets == 0)
    print('YES' if eligible else 'NO')
PY
)
printf 'WEEK32_RECOVERY_ELIGIBLE|%s\n' "$week32_recovery" >> "$EVIDENCE_FILE"
if [ "$week32_recovery" = "YES" ]; then
  mkdir -p instance/backups
  stamp=$(date +%Y%m%d-%H%M%S)
  venv/bin/python sqlite_online_backup.py instance/ipm.db "instance/backups/ipm-week32-recovery-${stamp}.db" >> "$EVIDENCE_FILE" 2>&1
  venv/bin/python scripts/requeue_latest_empty_ims.py --year 2026 --month 8 --week 32 >> "$EVIDENCE_FILE" 2>&1
  for poll in $(seq 1 180); do
    state=$(venv/bin/python - <<'PY'
from app import create_app
from app.models import IMSImportJob
from config import Config
app = create_app(Config)
with app.app_context():
    job = IMSImportJob.query.order_by(IMSImportJob.id.desc()).first()
    print('MISSING' if job is None else job.status)
PY
)
    printf 'WEEK32_RECOVERY_STATUS|poll=%s|state=%s\n' "$poll" "$state" >> "$EVIDENCE_FILE"
    case "$state" in
      COMPLETED) break ;;
      FAILED|MISSING) exit 1 ;;
    esac
    if [ "$poll" = 180 ]; then
      printf 'WEEK32_RECOVERY_TIMEOUT\n' >> "$EVIDENCE_FILE"
      exit 1
    fi
    sleep 10
  done
  venv/bin/python verify_live_ims_gate.py >> "$EVIDENCE_FILE" 2>&1
  printf 'WEEK32_RECOVERY_RESULT|PASS\n' >> "$EVIDENCE_FILE"
fi

printf '%s\n' '--- WEEKLY CAPACITY/PLANNER MAINTENANCE ---' >> "$EVIDENCE_FILE"
venv/bin/python database_capacity_audit.py \
  --database instance/ipm.db \
  --additional-uploads 49 \
  --optimize >> "$EVIDENCE_FILE" 2>&1

printf '%s\n' 'BACKUPS_BEFORE' >> "$EVIDENCE_FILE"
find instance/backups -maxdepth 1 -type f -printf '%12s %f\n' 2>/dev/null | sort -nr >> "$EVIDENCE_FILE" || true
printf '%s\n' 'STORAGE_BEFORE' >> "$EVIDENCE_FILE"
du -sh instance instance/backups uploads/ims_archive 2>/dev/null >> "$EVIDENCE_FILE" || true
df -h / >> "$EVIDENCE_FILE"

printf '%s\n' 'ROOT_STORAGE_BREAKDOWN_BYTES' >> "$EVIDENCE_FILE"
sudo du -x -B1 --max-depth=1 / 2>/dev/null | sort -nr | head -n 30 >> "$EVIDENCE_FILE" || true
printf '%s\n' 'HOME_STORAGE_BREAKDOWN_BYTES' >> "$EVIDENCE_FILE"
sudo du -x -B1 --max-depth=2 /home 2>/dev/null | sort -nr | head -n 60 >> "$EVIDENCE_FILE" || true
printf '%s\n' 'PROJECT_STORAGE_BREAKDOWN_BYTES' >> "$EVIDENCE_FILE"
du -x -B1 --max-depth=3 "$IMS_PATH" 2>/dev/null | sort -nr | head -n 120 >> "$EVIDENCE_FILE" || true
printf '%s\n' 'LARGE_FILES_OVER_100M_BYTES' >> "$EVIDENCE_FILE"
sudo find / -xdev -type f -size +100M -printf '%s %p\n' 2>/dev/null | sort -nr | head -n 120 >> "$EVIDENCE_FILE" || true

backup_count=$(find instance/backups -maxdepth 1 -type f -name 'ipm-predeploy-*.db' 2>/dev/null | wc -l)
printf 'MAINTENANCE_BACKUP_RETENTION|keep_latest=1|found=%s\n' "$backup_count" >> "$EVIDENCE_FILE"
if [ "$backup_count" -gt 0 ]; then
  venv/bin/python cleanup_old_backups.py --backup-dir instance/backups --keep-latest 1 --purge-unmanaged-db >> "$EVIDENCE_FILE" 2>&1
else
  printf 'MAINTENANCE_BACKUP_SET|status=none\n' >> "$EVIDENCE_FILE"
fi

printf '%s\n' 'KEPT_BACKUPS' >> "$EVIDENCE_FILE"
find instance/backups -maxdepth 1 -type f -printf '%12s %f\n' 2>/dev/null | sort -nr >> "$EVIDENCE_FILE" || true
printf '%s\n' 'STORAGE_AFTER' >> "$EVIDENCE_FILE"
du -sh instance instance/backups uploads/ims_archive 2>/dev/null >> "$EVIDENCE_FILE" || true
df -h / >> "$EVIDENCE_FILE"
free -h >> "$EVIDENCE_FILE"

venv/bin/python - <<'PY' >> "$EVIDENCE_FILE"
from app import create_app
from app.extensions import db
app = create_app()
with app.app_context():
    connection = db.session.connection()
    mode = str(connection.exec_driver_sql('PRAGMA journal_mode').scalar())
    timeout = int(connection.exec_driver_sql('PRAGMA busy_timeout').scalar())
    quick = str(connection.exec_driver_sql('PRAGMA quick_check(1)').scalar())
    print('SQLITE_JOURNAL_MODE|' + mode)
    print('SQLITE_BUSY_TIMEOUT|' + str(timeout))
    print('SQLITE_QUICK_CHECK|' + quick)
    assert mode.lower() == 'wal'
    assert timeout == 30000
    assert quick.lower() == 'ok'
PY

printf 'WEB_ACTIVE|%s\n' "$(sudo systemctl is-active ims-performance-manager.service)" >> "$EVIDENCE_FILE"
printf 'WORKER_ACTIVE|%s\n' "$(sudo systemctl is-active ims-import-worker.service)" >> "$EVIDENCE_FILE"
test "$(sudo systemctl is-active ims-performance-manager.service)" = "active"
test "$(sudo systemctl is-active ims-import-worker.service)" = "active"
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8000/login >/dev/null
printf 'HTTP_HEALTH|PASS\n' >> "$EVIDENCE_FILE"
venv/bin/python production_resource_gate.py --database instance/ipm.db --acceptance-seconds 0 >> "$EVIDENCE_FILE" 2>&1
