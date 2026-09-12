#!/usr/bin/env bash
# Week 32 failed-import diagnostic trigger: 2026-09-12
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
export PYTHONPATH="$IMS_PATH${PYTHONPATH:+:$PYTHONPATH}"
printf 'LIVE_COMMIT|%s\n' "$(git rev-parse HEAD)" >> "$EVIDENCE_FILE"
test "$(git branch --show-current)" = "main"
test -z "$(git status --porcelain)"

processing=$(venv/bin/python - <<'PY'
import sqlite3
from pathlib import Path
database = Path('instance/ipm.db')
if not database.exists():
    print(0); raise SystemExit(0)
connection = sqlite3.connect(database, timeout=30)
try:
    connection.execute('PRAGMA busy_timeout=30000')
    exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ims_import_jobs'").fetchone()
    value = 0 if not exists else int(connection.execute("SELECT COUNT(*) FROM ims_import_jobs WHERE status IN ('QUEUED','PROCESSING')").fetchone()[0])
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

# If the latest Week 32 retry failed, expose the persisted importer error first.
# This is read-only and deliberately does not create another backup or retry.
failed_week32=$(venv/bin/python - <<'PY'
from app import create_app
from app.models import IMSImportJob
from config import Config
app=create_app(Config)
with app.app_context():
    job=IMSImportJob.query.filter_by(year=2026, month=8).order_by(IMSImportJob.id.desc()).first()
    print('YES' if job and job.status == IMSImportJob.STATUS_FAILED else 'NO')
PY
)
printf 'WEEK32_FAILED_DIAGNOSTIC|%s\n' "$failed_week32" >> "$EVIDENCE_FILE"
if [ "$failed_week32" = "YES" ]; then
  venv/bin/python - <<'PY' >> "$EVIDENCE_FILE"
from app import create_app
from app.models import IMSImportJob, IMSUpload, Target
from config import Config
app=create_app(Config)
with app.app_context():
    job=IMSImportJob.query.filter_by(year=2026, month=8).order_by(IMSImportJob.id.desc()).first()
    upload=IMSUpload.query.get(job.ims_upload_id) if job and job.ims_upload_id else None
    print('FAILED_JOB|id=%s|upload=%s|error=%r|result=%r' % (job.id, job.ims_upload_id, job.error_message, job.result_summary))
    print('FAILED_UPLOAD|id=%s|status=%s|error=%r|warning=%r' % (getattr(upload,'id',None), getattr(upload,'status',None), getattr(upload,'error_message',None), getattr(upload,'warning_message',None)))
    print('TARGET_COUNT|%s' % Target.query.filter_by(year=2026, month=8).count())
PY
  printf '%s\n' '--- WORKER JOURNAL TAIL ---' >> "$EVIDENCE_FILE"
  sudo journalctl -u ims-import-worker.service -n 250 --no-pager >> "$EVIDENCE_FILE" 2>&1 || true
  exit 1
fi

week32_recovery=$(venv/bin/python - <<'PY'
from app import create_app
from app.models import IMSUpload, Target
from config import Config
app = create_app(Config)
with app.app_context():
    latest = IMSUpload.query.filter_by(status=IMSUpload.STATUS_COMPLETED).order_by(IMSUpload.year.desc(), IMSUpload.month.desc(), IMSUpload.week_number.desc(), IMSUpload.completed_at.desc(), IMSUpload.id.desc()).first()
    targets = Target.query.filter_by(year=2026, month=8).count()
    eligible = bool(latest and int(latest.year) == 2026 and int(latest.month) == 8 and int(latest.week_number) == 32 and targets == 0)
    print('YES' if eligible else 'NO')
PY
)
printf 'WEEK32_NORMAL_REIMPORT_ELIGIBLE|%s\n' "$week32_recovery" >> "$EVIDENCE_FILE"
if [ "$week32_recovery" = "YES" ]; then
  printf 'WEEK32_BACKUP_REUSED|new_backup=NO|reason=validated_pre_recovery_backup_exists\n' >> "$EVIDENCE_FILE"
  sudo systemctl restart ims-import-worker.service
  test "$(sudo systemctl is-active ims-import-worker.service)" = "active"
  printf 'IMS_WORKER_RELOADED|commit=%s\n' "$(git rev-parse HEAD)" >> "$EVIDENCE_FILE"
  venv/bin/python -m scripts.requeue_latest_empty_ims --year 2026 --month 8 --week 32 >> "$EVIDENCE_FILE" 2>&1
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
    printf 'WEEK32_NORMAL_REIMPORT_STATUS|poll=%s|state=%s\n' "$poll" "$state" >> "$EVIDENCE_FILE"
    case "$state" in
      COMPLETED) break ;;
      FAILED|MISSING) exit 1 ;;
    esac
    if [ "$poll" = 180 ]; then printf 'WEEK32_NORMAL_REIMPORT_TIMEOUT\n' >> "$EVIDENCE_FILE"; exit 1; fi
    sleep 10
  done
  venv/bin/python verify_live_ims_gate.py >> "$EVIDENCE_FILE" 2>&1
  printf 'WEEK32_NORMAL_REIMPORT_RESULT|PASS\n' >> "$EVIDENCE_FILE"
  exit 0
fi

printf 'MAINTENANCE_SKIPPED|reason=no_week32_action\n' >> "$EVIDENCE_FILE"
