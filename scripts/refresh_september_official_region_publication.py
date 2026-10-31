"""Refresh September read models without reimporting any business source.

Run only with the idle import worker stopped; the caller restores it on exit.
August/closed production periods and October publications are not rebuilt.
"""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import create_app
from app.extensions import db
from app.models import IMSImportJob,IMSUpload
from app.services.ims_progress_store import IMSProgressStore
from app.services.production_result_service import ProductionResultService
from app.services.ims_upload_lifecycle_service import IMSUploadLifecycleService
from ims_import_worker import _warm_dashboard_snapshot,_warm_region_snapshots,_prepare_and_publish


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--upload',type=int,required=True)
    args=parser.parse_args()
    app=create_app()
    with app.app_context():
        if IMSImportJob.query.filter(IMSImportJob.status.in_(('QUEUED','PROCESSING'))).count():
            raise RuntimeError('Active import prevents September refresh')
        upload=db.session.get(IMSUpload,args.upload)
        if not upload or (upload.year,upload.month,upload.status)!=(2026,9,'COMPLETED'):
            raise RuntimeError('Only accepted September 2026 is authorized')
        if ProductionResultService.final_upload(2026,9) is not None:
            raise RuntimeError('Closed production period cannot be refreshed')
        latest=IMSUpload.query.filter_by(year=2026,month=9,status='COMPLETED').order_by(IMSUpload.week_number.desc(),IMSUpload.id.desc()).first()
        if latest.id!=args.upload:
            raise RuntimeError('September source changed; inspect before retry')
        job=IMSImportJob.query.filter_by(ims_upload_id=args.upload,status='COMPLETED').order_by(IMSImportJob.id.desc()).first()
        if not job:
            raise RuntimeError('Completed durable source job is required')
        if not IMSUploadLifecycleService.snapshot_master_state_sealed(upload_id=args.upload):
            raise RuntimeError('Historical source journal is not sealed; do not synchronize the latest roster')
        job_id=job.id
        summary=json.loads(job.result_summary or '{}')
        summary['publication_ready']=False
        summary['september_official_region_refresh']=True
        job.result_summary=json.dumps(summary)
        db.session.commit()
        IMSProgressStore.write(job_id,percent=98,stage='snapshot_retry',
            message='Eylül resmi bölge kaynağı ekranları güncelleniyor',status='PROCESSING')
        dashboard=_warm_dashboard_snapshot(app,2026,9,force=True)
        if dashboard.get('status')!='ACTIVE':
            raise RuntimeError(f'Dashboard refresh failed: {dashboard}')
        region=_warm_region_snapshots(app,2026,9,force=True)
        if region.get('status')!='ACTIVE':
            raise RuntimeError(f'Region refresh failed: {region}')
        # The normal gate reuses already accepted representative source rows,
        # enriches exact-source region payloads, and publishes only when ready.
        job=db.session.get(IMSImportJob,job_id)
        if not _prepare_and_publish(app,job):
            raise RuntimeError('Normal September publication gate is not ready')
        print('SEPTEMBER_PUBLICATION_REFRESH|'+json.dumps(dict(result='PASS',upload_id=args.upload,job_id=job_id,dashboard=dashboard,region=region),default=str),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
