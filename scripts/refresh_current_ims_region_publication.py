"""Rebuild the current region generation through the normal publication gate.

Run with the idle IMS worker stopped; the caller must restore it on exit.
Historical sources/snapshots and current business facts are never rewritten.
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
from app.services.persistent_region_snapshot_service import PersistentRegionSnapshotService
from app.services.region_performance_service import RegionPerformanceService
from ims_import_worker import _prepare_and_publish


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--job',type=int,required=True);args=parser.parse_args()
    app=create_app()
    with app.app_context():
        if IMSImportJob.query.filter(IMSImportJob.status.in_(('QUEUED','PROCESSING'))).count():
            raise RuntimeError('Active import prevents publication refresh')
        job=db.session.get(IMSImportJob,args.job)
        assert job and job.status=='COMPLETED'
        upload=db.session.get(IMSUpload,job.ims_upload_id)
        assert upload and upload.status=='COMPLETED'
        assert RegionPerformanceService._uses_official_region_only(upload.year,upload.month)
        latest=IMSUpload.query.filter_by(status='COMPLETED').order_by(IMSUpload.year.desc(),IMSUpload.month.desc(),IMSUpload.week_number.desc(),IMSUpload.id.desc()).first()
        assert latest.id==upload.id
        upload_id=int(upload.id)
        year,month=upload.year,upload.month
        summary=json.loads(job.result_summary or '{}')
        summary['publication_ready']=False
        summary['region_market_official_authority_refresh']=True
        job.result_summary=json.dumps(summary)
        db.session.commit()
        IMSProgressStore.write(job.id,percent=98,stage='snapshot_retry',
            message='Bölge resmi kaynak snapshotları yenileniyor',status='PROCESSING')
        region=PersistentRegionSnapshotService.build_for_period(year,month,force=True)
        assert region.get('status')=='ACTIVE',region
        enriched=PersistentRegionSnapshotService.enrich_for_period(year,month)
        assert enriched.get('status') in ('ENRICHED','REUSED'),enriched
        job=db.session.get(IMSImportJob,args.job)
        assert _prepare_and_publish(app,job),'Normal publication is not ready'
        print('IMS_REGION_PUBLICATION_REFRESH|'+json.dumps(dict(result='PASS',job_id=args.job,upload_id=upload_id,region=region,enrichment=enriched),default=str))
    return 0


if __name__=='__main__':raise SystemExit(main())
