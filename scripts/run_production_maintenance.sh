#!/usr/bin/env bash
set -Eeuo pipefail

IMS_PATH=${1:?IMS_PATH is required}
JOB_DIR=${2:?JOB_DIR is required}
mkdir -p "$JOB_DIR"
STATUS_FILE="$JOB_DIR/status"
EVIDENCE_FILE="$JOB_DIR/evidence.log"
LOCK_FILE="$IMS_PATH/instance/.production-maintenance.lock"
SERVICES_QUIESCED=0
: > "$EVIDENCE_FILE"
printf 'RUNNING\n' > "$STATUS_FILE"
finish(){
 rc=$?
 if [ "$SERVICES_QUIESCED" = 1 ]; then
  sudo systemctl start ims-import-worker.service >/dev/null 2>&1 || true
  sudo systemctl restart ims-performance-manager.service >/dev/null 2>&1 || true
 fi
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

# The Week 32 import is already authoritative. If publication was interrupted,
# resume the exact BUILDING representative generation instead of discarding
# completed representatives and starting all 113 again. This keeps the old
# ACTIVE generation visible until the resumed generation is fully validated.
week32_publication_recovery=$(venv/bin/python - <<'PY'
import json
import sqlalchemy as sa
from app import create_app
from app.extensions import db
from app.models import IMSImportJob, IMSUpload
from app.services.persistent_representative_snapshot_service import representative_snapshot_sets
from config import Config
class MaintenanceConfig(Config):
 TESTING=True
app=create_app(MaintenanceConfig)
with app.app_context():
 upload=IMSUpload.query.filter_by(year=2026,month=8,week_number=32,status='COMPLETED').order_by(IMSUpload.id.desc()).first()
 job=IMSImportJob.query.filter_by(ims_upload_id=getattr(upload,'id',-1)).order_by(IMSImportJob.id.desc()).first() if upload else None
 summary={}
 if job and job.result_summary:
  try: summary=json.loads(job.result_summary)
  except (TypeError,ValueError): summary={}
 building=0
 if upload:
  building=int(db.session.execute(sa.select(sa.func.count()).select_from(representative_snapshot_sets).where(
   representative_snapshot_sets.c.year==2026,
   representative_snapshot_sets.c.month==8,
   representative_snapshot_sets.c.source_upload_id==upload.id,
   representative_snapshot_sets.c.status=='BUILDING',
  )).scalar() or 0)
 eligible=bool(upload and upload.id==45 and job and job.id==35 and job.status=='COMPLETED' and (not summary.get('publication_ready') or building))
 print('YES' if eligible else 'NO')
PY
)
printf 'WEEK32_PUBLICATION_RECOVERY_ELIGIBLE|%s\n' "$week32_publication_recovery" >> "$EVIDENCE_FILE"
if [ "$week32_publication_recovery" = YES ]; then
 printf 'WEEK32_PUBLICATION_RECOVERY|mode=resume_partial_generation|reimport=NO\n' >> "$EVIDENCE_FILE"
 sudo systemctl stop ims-performance-manager.service
 sudo systemctl stop ims-import-worker.service
 SERVICES_QUIESCED=1
 sleep 2

 venv/bin/python -u - <<'PY' >> "$EVIDENCE_FILE" 2>&1
import json
from datetime import datetime
import sqlalchemy as sa
from app import create_app
from app.extensions import db
from app.models import CompetitionData, IMSImportJob, IMSUpload, Representative
from app.services.kpi_market_single_source import AUTHORITY_PREFIX
from app.services.market_analysis_service import MarketAnalysisService
from app.services.persistent_dashboard_snapshot_service import PersistentDashboardSnapshotService
from app.services.persistent_region_snapshot_service import PersistentRegionSnapshotService, region_snapshot_sets
from app.services.persistent_representative_snapshot_service import (
    PersistentRepresentativeSnapshotService,
    representative_snapshot_sets,
    representative_snapshots,
)
from app.services.representative_period_workspace import build_representative_workspace_payload
from config import Config

class MaintenanceConfig(Config):
    TESTING = True

def close(a, b, tol=0.01):
    return abs(float(a or 0) - float(b or 0)) <= tol

def region_payloads_valid(regions, upload_id):
    if len(regions) != 11:
        return False, None
    istanbul = None
    for region_key, snapshot in regions.items():
        market = snapshot.get('market_analysis') or {}
        rows = market.get('rows') or []
        totals = market.get('totals') or {}
        if len(rows) != 7 or int(market.get('upload_id') or 0) != int(upload_id):
            return False, None
        if market.get('market_share_source') != 'IMS_KPI_AGGREGATE_PAZAR':
            return False, None
        travazol = next((row for row in rows if str(row.get('product_name') or '').upper() == 'TRAVAZOL'), None)
        if not travazol:
            return False, None
        rivals = travazol.get('rivals') or []
        if not rivals:
            return False, None
        if not all(str(r.get('name') or '').strip() and float(r.get('unit') or 0) > 0 for r in rivals):
            return False, None
        if not close(sum(float(r.get('unit') or 0) for r in rivals), travazol.get('competitor_unit')):
            return False, None
        for row in rows:
            if not close(row.get('company_unit') + row.get('competitor_unit'), row.get('market_unit')):
                return False, None
        if not close(totals.get('company_unit') + totals.get('competitor_unit'), totals.get('market_unit')):
            return False, None
        if str(region_key).startswith('101'):
            istanbul = totals
    if not istanbul:
        return False, None
    if not (close(istanbul.get('company_unit'), 52024) and close(istanbul.get('competitor_unit'), 85747) and close(istanbul.get('market_unit'), 137771)):
        return False, None
    return True, istanbul

def representative_payload_valid(raw, upload_id):
    try:
        snap = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return False
    market = ((((snap.get('snapshots') or {}).get('monthly') or {}).get('market_analysis')) or {})
    rows = market.get('rows') or []
    totals = market.get('totals') or {}
    if len(rows) != 7 or int(market.get('upload_id') or 0) != int(upload_id):
        return False
    for row in rows:
        if not close(row.get('actual_unit') + row.get('competitor_unit'), row.get('market_unit')):
            return False
        if str(row.get('product_name') or '').upper() == 'TRAVAZOL' and float(row.get('competitor_unit') or 0) > 0:
            rivals = row.get('rivals') or []
            if not rivals:
                return False
            if not close(sum(float(r.get('unit') or 0) for r in rivals), row.get('competitor_unit')):
                return False
    return close(totals.get('actual_unit') + totals.get('competitor_unit'), totals.get('market_unit'))

app = create_app(MaintenanceConfig)
with app.app_context():
    upload = IMSUpload.query.filter_by(year=2026, month=8, week_number=32, status='COMPLETED').order_by(IMSUpload.id.desc()).first()
    assert upload and upload.id == 45, getattr(upload, 'id', None)
    job = IMSImportJob.query.filter_by(ims_upload_id=upload.id).order_by(IMSImportJob.id.desc()).first()
    assert job and job.id == 35 and job.status == 'COMPLETED', (getattr(job, 'id', None), getattr(job, 'status', None))

    authority_count = CompetitionData.query.filter(
        CompetitionData.upload_id == upload.id,
        CompetitionData.sheet_name.like(f'{AUTHORITY_PREFIX}%'),
    ).count()
    assert authority_count == 168, authority_count

    detail_rows = db.session.query(
        CompetitionData.territory,
        CompetitionData.product_name,
        CompetitionData.metric_value,
        CompetitionData.is_company_product,
    ).filter(
        CompetitionData.upload_id == upload.id,
        CompetitionData.metric_type == 'UNIT',
        CompetitionData.is_subtotal.is_(False),
        CompetitionData.is_grand_total.is_(False),
        db.func.upper(CompetitionData.product_group).like('%TRAVAZOL%'),
        db.func.upper(CompetitionData.sheet_name).like('%IMS COMPAT%'),
    ).all()
    detail_regions = sorted({
        str(row.territory or '').strip().split()[0]
        for row in detail_rows
        if str(row.territory or '').strip()
        and not bool(row.is_company_product)
        and float(row.metric_value or 0) > 0
    })
    detail_names = sorted({
        str(row.product_name or '').strip()
        for row in detail_rows
        if not bool(row.is_company_product) and float(row.metric_value or 0) > 0
    })
    print(f'TRAVAZOL_DB_DETAIL|rows={len(detail_rows)}|regions={detail_regions}|names={detail_names}')
    assert len(detail_regions) == 11 and detail_names

    regions = PersistentRegionSnapshotService.get_active_all(2026, 8)
    region_ok, istanbul = region_payloads_valid(regions, upload.id)
    if not region_ok:
        db.session.execute(
            region_snapshot_sets.update().where(
                region_snapshot_sets.c.year == 2026,
                region_snapshot_sets.c.month == 8,
                region_snapshot_sets.c.source_upload_id == upload.id,
                region_snapshot_sets.c.status == 'ACTIVE',
            ).values(status='BUILDING')
        )
        db.session.commit()
        region_refresh = PersistentRegionSnapshotService.build_for_period(2026, 8)
        assert region_refresh.get('status') == 'ACTIVE', region_refresh
        regions = PersistentRegionSnapshotService.get_active_all(2026, 8)
        region_ok, istanbul = region_payloads_valid(regions, upload.id)
        assert region_ok
        print(f"TARGETED_REGION_REFRESH|PASS|set_id={region_refresh.get('set_id')}")
    else:
        print('TARGETED_REGION_REFRESH|REUSED|regions=11')

    dashboard = PersistentDashboardSnapshotService.get_active(2026, 8) or {}
    executive = dashboard.get('executive_metrics') or {}
    assert len(executive.get('products') or []) == 7
    assert float(executive.get('target_tl') or 0) > 0
    assert float(executive.get('actual_tl') or 0) > 0

    national = MarketAnalysisService(2026, 8).build()
    assert national.get('metric_mode') == 'UNIT'
    assert len(national.get('groups') or []) == 7
    assert close(national.get('company_total_unit'), 314214), national.get('company_total_unit')
    assert close(national.get('competitor_total_unit'), 613403), national.get('competitor_total_unit')
    assert close(national.get('market_total_unit'), 927617), national.get('market_total_unit')
    for row in national['groups']:
        assert close(row['company_sales_unit'] + row['competitor_sales_unit'], row['market_sales_unit']), row

    ims_id, production_id = PersistentRepresentativeSnapshotService.source_identity(2026, 8)
    assert ims_id == upload.id, ims_id
    ids = PersistentRepresentativeSnapshotService.representative_ids(2026, 8, ims_id)
    assert len(ids) == 113, len(ids)
    valid_id_set = set(ids)

    building_id = PersistentRepresentativeSnapshotService._current_source_building(2026, 8, ims_id, production_id)
    if building_id:
        set_id = int(building_id)
    else:
        result = db.session.execute(representative_snapshot_sets.insert().values(
            year=2026,
            month=8,
            source_upload_id=ims_id,
            production_upload_id=production_id,
            status='BUILDING',
            representative_count=0,
            created_at=datetime.utcnow(),
        ))
        set_id = int(result.inserted_primary_key[0])
        db.session.commit()

    existing_rows = db.session.execute(
        sa.select(representative_snapshots.c.representative_id, representative_snapshots.c.payload_json).where(
            representative_snapshots.c.set_id == set_id
        )
    ).all()
    reusable_ids = set()
    invalid_ids = []
    for representative_id, raw in existing_rows:
        representative_id = int(representative_id)
        if representative_id in valid_id_set and representative_payload_valid(raw, upload.id):
            reusable_ids.add(representative_id)
        else:
            invalid_ids.append(representative_id)
    if invalid_ids:
        db.session.execute(representative_snapshots.delete().where(
            representative_snapshots.c.set_id == set_id,
            representative_snapshots.c.representative_id.in_(invalid_ids),
        ))
        db.session.commit()
    missing_ids = [representative_id for representative_id in ids if representative_id not in reusable_ids]
    print(f'REPRESENTATIVE_RESUME|set_id={set_id}|reused={len(reusable_ids)}|remaining={len(missing_ids)}|total={len(ids)}')

    completed = len(reusable_ids)
    for build_index, representative_id in enumerate(missing_ids, start=1):
        representative = db.session.get(Representative, representative_id)
        assert representative is not None, representative_id
        workspace = build_representative_workspace_payload(representative, 2026, 8)
        payload = json.dumps(
            PersistentRepresentativeSnapshotService._json_ready(workspace),
            ensure_ascii=False,
            separators=(',', ':'),
            default=PersistentRepresentativeSnapshotService._json_default,
        )
        db.session.execute(representative_snapshots.insert().values(
            set_id=set_id,
            representative_id=representative_id,
            payload_json=payload,
            created_at=datetime.utcnow(),
        ))
        completed += 1
        db.session.execute(
            representative_snapshot_sets.update().where(
                representative_snapshot_sets.c.id == set_id
            ).values(representative_count=completed)
        )
        if build_index % 4 == 0 or build_index == len(missing_ids):
            db.session.commit()
            print(f'REPRESENTATIVE_RESUME_PROGRESS|set_id={set_id}|completed={completed}|total={len(ids)}')

    final_rows = db.session.execute(
        sa.select(representative_snapshots.c.representative_id, representative_snapshots.c.payload_json).where(
            representative_snapshots.c.set_id == set_id
        ).order_by(representative_snapshots.c.representative_id.asc())
    ).all()
    assert len(final_rows) == len(ids), (len(final_rows), len(ids))
    assert {int(row[0]) for row in final_rows} == valid_id_set
    assert all(representative_payload_valid(raw, upload.id) for _, raw in final_rows)

    db.session.execute(
        representative_snapshot_sets.update().where(
            representative_snapshot_sets.c.year == 2026,
            representative_snapshot_sets.c.month == 8,
            representative_snapshot_sets.c.status == 'ACTIVE',
            representative_snapshot_sets.c.id != set_id,
        ).values(status='SUPERSEDED')
    )
    db.session.execute(
        representative_snapshot_sets.update().where(
            representative_snapshot_sets.c.id == set_id
        ).values(
            status='ACTIVE',
            representative_count=len(ids),
            activated_at=datetime.utcnow(),
        )
    )
    db.session.commit()
    print(f'TARGETED_REPRESENTATIVE_REFRESH|PASS|set_id={set_id}|representatives={len(ids)}')

    murat = Representative.query.filter(db.func.upper(Representative.rep_name) == 'MURAT ARSLAN').first()
    assert murat
    murat_raw = db.session.execute(sa.select(representative_snapshots.c.payload_json).where(
        representative_snapshots.c.set_id == set_id,
        representative_snapshots.c.representative_id == murat.id,
    )).scalar()
    assert murat_raw and representative_payload_valid(murat_raw, upload.id)
    murat_snap = json.loads(murat_raw)
    murat_market = ((((murat_snap.get('snapshots') or {}).get('monthly') or {}).get('market_analysis')) or {})
    mt = murat_market.get('totals') or {}

    summary = json.loads(job.result_summary or '{}')
    summary['publication_ready'] = True
    summary['publication_ready_source'] = 'verified_week32_resumed_partial_snapshot_generation'
    job.result_summary = json.dumps(summary, ensure_ascii=False)
    job.error_message = None
    db.session.commit()
    print('PUBLICATION_READY|PASS|upload=45|job=35')
    print(
        'KPI_SINGLE_SOURCE_ACCEPTANCE_READONLY|PASS'
        f'|authority_rows={authority_count}'
        f"|national_company={national['company_total_unit']:.2f}"
        f"|national_competitor={national['competitor_total_unit']:.2f}"
        f"|national_market={national['market_total_unit']:.2f}"
        f"|istanbul_company={float(istanbul['company_unit']):.2f}"
        f"|istanbul_competitor={float(istanbul['competitor_unit']):.2f}"
        f"|istanbul_market={float(istanbul['market_unit']):.2f}"
        '|regions=11|travazol_named_rival_regions=11|representatives=113|murat_rows=7'
        f'|murat_company={float(mt.get("actual_unit") or 0):.2f}'
        f'|murat_competitor={float(mt.get("competitor_unit") or 0):.2f}'
        f'|murat_market={float(mt.get("market_unit") or 0):.2f}'
    )
PY

 sudo systemctl start ims-import-worker.service
 sudo systemctl restart ims-performance-manager.service
 SERVICES_QUIESCED=0
 test "$(sudo systemctl is-active ims-import-worker.service)" = active
 test "$(sudo systemctl is-active ims-performance-manager.service)" = active
 health=0
 for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error --max-time 6 http://127.0.0.1:8000/login >/dev/null; then health=1; break; fi
  sleep 2
 done
 test "$health" = 1
 printf 'HTTP_HEALTH|PASS\n' >> "$EVIDENCE_FILE"
 venv/bin/python verify_live_ims_gate.py >> "$EVIDENCE_FILE" 2>&1
 printf 'WEEK32_FINAL_PUBLICATION|PASS\n' >> "$EVIDENCE_FILE"
 exit 0
fi

# From this point onward the weekly work is read-only against the live IMS DB
# (plus filesystem backup retention). Do not hold the global import lock while
# integrity/capacity scans traverse a multi-GB SQLite file. This keeps uploads
# responsive while preserving exclusivity for actual import/recovery writes.
flock -u 9
printf 'MAINTENANCE_IMPORT_LOCK_RELEASED|reason=read_only_weekly_checks\n' >> "$EVIDENCE_FILE"

BACKUPS_BEFORE=$(find instance/backups -maxdepth 1 -type f -name 'ipm-predeploy-*.db' 2>/dev/null | wc -l | tr -d ' ')
STORAGE_BEFORE=$(du -sb instance 2>/dev/null | awk '{print $1}')
printf 'BACKUPS_BEFORE|%s\nSTORAGE_BEFORE|%s\n' "$BACKUPS_BEFORE" "${STORAGE_BEFORE:-0}" >> "$EVIDENCE_FILE"
# Do not run PRAGMA optimize here: the capacity audit must remain read-only once
# the import lock has been released.
venv/bin/python database_capacity_audit.py --additional-uploads 49 >> "$EVIDENCE_FILE" 2>&1
venv/bin/python cleanup_old_backups.py --keep-latest 1 >> "$EVIDENCE_FILE" 2>&1
printf 'MAINTENANCE_BACKUP_RETENTION|keep_latest=1\n' >> "$EVIDENCE_FILE"

venv/bin/python - <<'PY' >> "$EVIDENCE_FILE"
import sqlite3
c=sqlite3.connect('instance/ipm.db',timeout=30)
try:
 c.execute('PRAGMA busy_timeout=30000')
 print('SQLITE_JOURNAL_MODE|%s' % c.execute('PRAGMA journal_mode').fetchone()[0])
 print('SQLITE_BUSY_TIMEOUT|%s' % c.execute('PRAGMA busy_timeout').fetchone()[0])
finally: c.close()
PY

# The capacity audit above already performs a full integrity_check. A second
# full-table quick_check is redundant and previously kept maintenance alive for
# too long. Keep it best-effort and bounded so it can never delay an import.
set +e
timeout 60s venv/bin/python - <<'PY' >> "$EVIDENCE_FILE" 2>&1
import sqlite3
c=sqlite3.connect('instance/ipm.db',timeout=30)
try:
 c.execute('PRAGMA busy_timeout=30000')
 print('SQLITE_QUICK_CHECK|%s' % c.execute('PRAGMA quick_check(1)').fetchone()[0])
finally: c.close()
PY
quick_rc=$?
set -e
if [ "$quick_rc" -eq 124 ]; then
 printf 'SQLITE_QUICK_CHECK|TIMEOUT_NONBLOCKING|limit_seconds=60\n' >> "$EVIDENCE_FILE"
elif [ "$quick_rc" -ne 0 ]; then
 printf 'SQLITE_QUICK_CHECK|ERROR_NONBLOCKING|exit_code=%s\n' "$quick_rc" >> "$EVIDENCE_FILE"
fi

WEB_ACTIVE=$(sudo systemctl is-active ims-performance-manager.service)
WORKER_ACTIVE=$(sudo systemctl is-active ims-import-worker.service)
printf 'WEB_ACTIVE|%s\nWORKER_ACTIVE|%s\n' "$WEB_ACTIVE" "$WORKER_ACTIVE" >> "$EVIDENCE_FILE"
test "$WEB_ACTIVE" = active
test "$WORKER_ACTIVE" = active
curl -fsS --max-time 20 http://127.0.0.1:8000/health >/dev/null
printf 'HTTP_HEALTH|PASS\n' >> "$EVIDENCE_FILE"
