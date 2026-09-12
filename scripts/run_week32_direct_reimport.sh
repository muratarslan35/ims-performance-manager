#!/usr/bin/env bash
set -Eeuo pipefail

IMS_PATH=${1:-/home/ubuntu/ims_system}
cd "$IMS_PATH"
export PYTHONPATH="$IMS_PATH${PYTHONPATH:+:$PYTHONPATH}"

# Do not interrupt production maintenance. Wait for its lock, then run only the
# normal IMS replacement import and the worker-owned snapshot publication path.
exec 9>instance/.production-maintenance.lock
if ! flock -w 3600 9; then
  echo 'WEEK32_DIRECT_REIMPORT_REFUSED|reason=maintenance_lock_timeout'
  exit 1
fi

test "$(git branch --show-current)" = main
test -z "$(git status --porcelain)"
git fetch origin main
git pull --ff-only origin main
echo "LIVE_COMMIT|$(git rev-parse HEAD)"

active=$(venv/bin/python - <<'PY'
from app import create_app
from app.models import IMSImportJob
from config import Config
app = create_app(Config)
with app.app_context():
    count = IMSImportJob.query.filter(
        IMSImportJob.status.in_((IMSImportJob.STATUS_QUEUED, IMSImportJob.STATUS_PROCESSING))
    ).count()
    print(count)
PY
)
echo "IMS_PROCESSING|$active"
test "$active" = 0

sudo systemctl restart ims-import-worker.service
test "$(sudo systemctl is-active ims-import-worker.service)" = active
echo "IMS_WORKER_RELOADED|commit=$(git rev-parse HEAD)"

venv/bin/python -m scripts.requeue_latest_empty_ims \
  --year 2026 --month 8 --week 32 --allow-existing-targets

for poll in $(seq 1 180); do
  state=$(venv/bin/python - <<'PY'
import json
from app import create_app
from app.models import IMSImportJob
from config import Config
app = create_app(Config)
with app.app_context():
    job = IMSImportJob.query.order_by(IMSImportJob.id.desc()).first()
    if job is None:
        print('MISSING|0')
    else:
        try:
            summary = json.loads(job.result_summary or '{}')
        except Exception:
            summary = {}
        print(f"{job.status}|{int(bool(summary.get('publication_ready')))}")
PY
  )
  status=${state%%|*}
  ready=${state##*|}
  echo "WEEK32_DIRECT_REIMPORT_STATUS|poll=$poll|state=$status|publication_ready=$ready"

  if [ "$status" = FAILED ] || [ "$status" = MISSING ]; then
    venv/bin/python - <<'PY'
from app import create_app
from app.models import IMSImportJob, IMSUpload
from config import Config
app = create_app(Config)
with app.app_context():
    job = IMSImportJob.query.order_by(IMSImportJob.id.desc()).first()
    upload = IMSUpload.query.get(job.ims_upload_id) if job and job.ims_upload_id else None
    print('FAILED_JOB|id=%s|error=%r|result=%r' % (
        getattr(job, 'id', None), getattr(job, 'error_message', None), getattr(job, 'result_summary', None)
    ))
    print('FAILED_UPLOAD|id=%s|status=%s|error=%r|warning=%r' % (
        getattr(upload, 'id', None), getattr(upload, 'status', None),
        getattr(upload, 'error_message', None), getattr(upload, 'warning_message', None)
    ))
PY
    exit 1
  fi

  if [ "$status" = COMPLETED ] && [ "$ready" = 1 ]; then
    break
  fi
  if [ "$poll" = 180 ]; then
    echo 'WEEK32_DIRECT_REIMPORT_TIMEOUT'
    exit 1
  fi
  sleep 10
done

venv/bin/python verify_live_ims_gate.py
echo 'WEEK32_DIRECT_REIMPORT_RESULT|PASS'
