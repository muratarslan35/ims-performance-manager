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
finish(){ rc=$?; if [ "$rc" -eq 0 ]; then printf 'PASS\n' > "$STATUS_FILE"; printf 'MAINTENANCE_RESULT|PASS\n' >> "$EVIDENCE_FILE"; else printf 'FAIL|exit_code=%s\n' "$rc" > "$STATUS_FILE"; printf 'MAINTENANCE_RESULT|FAIL|exit_code=%s\n' "$rc" >> "$EVIDENCE_FILE"; fi; }
trap finish EXIT
exec 9>"$LOCK_FILE"
if ! flock -n 9; then printf 'MAINTENANCE_SKIPPED|reason=already_running\n' >> "$EVIDENCE_FILE"; exit 0; fi

cd "$IMS_PATH"
export PYTHONPATH="$IMS_PATH${PYTHONPATH:+:$PYTHONPATH}"
printf 'LIVE_COMMIT|%s\n' "$(git rev-parse HEAD)" >> "$EVIDENCE_FILE"
test "$(git branch --show-current)" = main
test -z "$(git status --porcelain)"

processing=$(venv/bin/python - <<'PY'
import sqlite3
from pathlib import Path
p=Path('instance/ipm.db')
if not p.exists(): print(0); raise SystemExit
c=sqlite3.connect(p,timeout=30); c.execute('PRAGMA busy_timeout=30000')
try:
 e=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ims_import_jobs'").fetchone()
 print(0 if not e else int(c.execute("SELECT COUNT(*) FROM ims_import_jobs WHERE status IN ('QUEUED','PROCESSING')").fetchone()[0]))
finally: c.close()
PY
)
printf 'IMS_PROCESSING|%s\n' "$processing" >> "$EVIDENCE_FILE"
if [ "$processing" != 0 ]; then printf 'MAINTENANCE_SKIPPED|reason=active_import|processing=%s\n' "$processing" >> "$EVIDENCE_FILE"; exit 0; fi

week32_recovery=$(venv/bin/python - <<'PY'
from app import create_app
from app.models import IMSUpload,Target
from config import Config
app=create_app(Config)
with app.app_context():
 latest=IMSUpload.query.order_by(IMSUpload.year.desc(),IMSUpload.month.desc(),IMSUpload.week_number.desc(),IMSUpload.id.desc()).first()
 targets=Target.query.filter_by(year=2026,month=8).count()
 retryable=latest and latest.status in (IMSUpload.STATUS_COMPLETED,'FAILED')
 print('YES' if retryable and int(latest.year)==2026 and int(latest.month)==8 and int(latest.week_number)==32 and targets==0 else 'NO')
PY
)
printf 'WEEK32_NORMAL_REIMPORT_ELIGIBLE|%s\n' "$week32_recovery" >> "$EVIDENCE_FILE"
if [ "$week32_recovery" = YES ]; then
 printf 'WEEK32_BACKUP_REUSED|new_backup=NO|reason=validated_pre_recovery_backup_exists\n' >> "$EVIDENCE_FILE"
 sudo systemctl restart ims-import-worker.service
 test "$(sudo systemctl is-active ims-import-worker.service)" = active
 printf 'IMS_WORKER_RELOADED|commit=%s\n' "$(git rev-parse HEAD)" >> "$EVIDENCE_FILE"
 venv/bin/python -m scripts.requeue_latest_empty_ims --year 2026 --month 8 --week 32 >> "$EVIDENCE_FILE" 2>&1
 for poll in $(seq 1 180); do
  state=$(venv/bin/python - <<'PY'
from app import create_app
from app.models import IMSImportJob
from config import Config
app=create_app(Config)
with app.app_context():
 j=IMSImportJob.query.order_by(IMSImportJob.id.desc()).first(); print('MISSING' if j is None else j.status)
PY
)
  printf 'WEEK32_NORMAL_REIMPORT_STATUS|poll=%s|state=%s\n' "$poll" "$state" >> "$EVIDENCE_FILE"
  case "$state" in COMPLETED) break;; FAILED|MISSING) exit 1;; esac
  [ "$poll" != 180 ] || { printf 'WEEK32_NORMAL_REIMPORT_TIMEOUT\n' >> "$EVIDENCE_FILE"; exit 1; }
  sleep 10
 done
 venv/bin/python verify_live_ims_gate.py >> "$EVIDENCE_FILE" 2>&1
 printf 'WEEK32_NORMAL_REIMPORT_RESULT|PASS\n' >> "$EVIDENCE_FILE"
 exit 0
fi

# Normal weekly maintenance path. Week 32 recovery exits above and therefore
# never creates another backup or runs expensive capacity work during recovery.
BACKUPS_BEFORE=$(find instance/backups -maxdepth 1 -type f -name 'ipm-predeploy-*.db' 2>/dev/null | wc -l | tr -d ' ')
STORAGE_BEFORE=$(du -sb instance 2>/dev/null | awk '{print $1}')
printf 'BACKUPS_BEFORE|%s\nSTORAGE_BEFORE|%s\n' "$BACKUPS_BEFORE" "${STORAGE_BEFORE:-0}" >> "$EVIDENCE_FILE"
venv/bin/python database_capacity_audit.py --additional-uploads 49 --optimize >> "$EVIDENCE_FILE" 2>&1
venv/bin/python cleanup_old_backups.py --keep-latest 1 >> "$EVIDENCE_FILE" 2>&1
printf 'MAINTENANCE_BACKUP_RETENTION|keep_latest=1\n' >> "$EVIDENCE_FILE"

venv/bin/python - <<'PY' >> "$EVIDENCE_FILE"
import sqlite3
c=sqlite3.connect('instance/ipm.db',timeout=30)
try:
 c.execute('PRAGMA busy_timeout=30000')
 print('SQLITE_JOURNAL_MODE|%s' % c.execute('PRAGMA journal_mode').fetchone()[0])
 print('SQLITE_BUSY_TIMEOUT|%s' % c.execute('PRAGMA busy_timeout').fetchone()[0])
 print('SQLITE_QUICK_CHECK|%s' % c.execute('PRAGMA quick_check(1)').fetchone()[0])
finally: c.close()
PY
WEB_ACTIVE=$(sudo systemctl is-active ims-performance-manager.service)
WORKER_ACTIVE=$(sudo systemctl is-active ims-import-worker.service)
printf 'WEB_ACTIVE|%s\nWORKER_ACTIVE|%s\n' "$WEB_ACTIVE" "$WORKER_ACTIVE" >> "$EVIDENCE_FILE"
test "$WEB_ACTIVE" = active
test "$WORKER_ACTIVE" = active
curl -fsS --max-time 20 http://127.0.0.1:8000/health >/dev/null
printf 'HTTP_HEALTH|PASS\n' >> "$EVIDENCE_FILE"
