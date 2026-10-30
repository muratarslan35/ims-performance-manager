"""Explicit operator replay through the normal durable IMS queue.

Preserves the prior completed upload/snapshots until the replacement publishes.
Does not edit facts, targets, prices, or snapshot payloads directly.
"""
import argparse
import hashlib
import json
import shutil
import uuid
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import sqlalchemy as sa
from app import create_app
from app.extensions import db
from app.models import IMSImportJob, IMSUpload
from app.services.ims_upload_lifecycle_service import IMSUploadLifecycleService
from app.services.production_result_service import ProductionResultService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-upload', type=int, required=True)
    args = parser.parse_args()
    app = create_app()
    with app.app_context():
        source_upload = db.session.get(IMSUpload, args.source_upload)
        if source_upload is None or source_upload.status != 'COMPLETED':
            raise RuntimeError('Replay requires a completed source upload')
        if ProductionResultService.final_upload(source_upload.year, source_upload.month):
            raise RuntimeError('Closed production period cannot be replayed')
        source = IMSUploadLifecycleService.archived_source_for_upload(source_upload.id)
        if source is None:
            raise RuntimeError('Verified archived source is missing')
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        marker = ROOT / 'instance' / f'official-region-replay-{source_upload.id}.json'
        if marker.is_file():
            saved = json.loads(marker.read_text())
            job = db.session.get(IMSImportJob, int(saved['job_id']))
            if job and job.source_hash == digest and job.status in ('QUEUED','PROCESSING','COMPLETED'):
                print('IMS_OFFICIAL_REGION_REPLAY|' + json.dumps(saved))
                return 0
        queue = Path(app.config['UPLOAD_FOLDER']) / 'ims_queue'
        queue.mkdir(parents=True, exist_ok=True)
        stored = uuid.uuid4().hex + '-' + source_upload.file_name
        destination = queue / stored
        shutil.copy2(source, destination)
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            destination.unlink(); raise RuntimeError('Staging hash mismatch')
        file_name, year, month, week = source_upload.file_name, source_upload.year, source_upload.month, source_upload.week_number
        db.session.rollback()
        try:
            db.session.execute(sa.text('BEGIN IMMEDIATE'))
            if IMSImportJob.query.filter(IMSImportJob.status.in_(('QUEUED','PROCESSING'))).count():
                raise RuntimeError('Another IMS import is active')
            latest = IMSUpload.query.filter_by(status='COMPLETED').order_by(IMSUpload.year.desc(),IMSUpload.month.desc(),IMSUpload.week_number.desc(),IMSUpload.id.desc()).first()
            if latest is None or latest.id != args.source_upload:
                raise RuntimeError('Replay source is no longer the latest completed IMS')
            job = IMSImportJob(status='QUEUED',file_name=file_name,stored_file_name=stored,
                source_hash=digest,year=year,month=month,clear_before_import=True,
                uploaded_by='AUTHORIZED_OFFICIAL_REGION_REIMPORT')
            db.session.add(job); db.session.commit()
        except Exception:
            db.session.rollback(); destination.unlink(missing_ok=True); raise
        saved = dict(job_id=job.id,previous_upload_id=args.source_upload,year=year,month=month,week=week,sha256=digest)
        marker.write_text(json.dumps(saved), encoding='utf-8')
        print('IMS_OFFICIAL_REGION_REPLAY|' + json.dumps(saved))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
