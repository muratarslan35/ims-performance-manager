"""Requeue the latest completed IMS with empty targets through the normal worker.

This recovery deliberately does not roll the database back. It validates the
archived workbook and its original queue identity, stages that exact workbook,
and queues the existing upload/job with clear_before_import=True. The regular
IMS worker remains the only component that performs the replacement import and
snapshot/publication flow.
"""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

from app import create_app
from app.extensions import db
from app.models import IMSImportJob, IMSUpload, Target
from app.services.ims_upload_lifecycle_service import IMSUploadLifecycleService
from config import Config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--actor", default="GitHub production recovery")
    args = parser.parse_args()

    app = create_app(Config)
    with app.app_context():
        active = IMSImportJob.query.filter(
            IMSImportJob.status.in_((IMSImportJob.STATUS_QUEUED, IMSImportJob.STATUS_PROCESSING))
        ).count()
        if active:
            raise SystemExit(f"RECOVERY_REFUSED|active_jobs={active}")

        upload = (
            IMSUpload.query.filter_by(
                year=args.year,
                month=args.month,
                week_number=args.week,
                status=IMSUpload.STATUS_COMPLETED,
            )
            .order_by(IMSUpload.completed_at.desc(), IMSUpload.id.desc())
            .first()
        )
        if upload is None:
            raise SystemExit("RECOVERY_REFUSED|reason=completed_upload_not_found")

        global_latest = IMSUpload.query.filter_by(status=IMSUpload.STATUS_COMPLETED).order_by(
            IMSUpload.year.desc(), IMSUpload.month.desc(), IMSUpload.week_number.desc(),
            IMSUpload.completed_at.desc(), IMSUpload.id.desc(),
        ).first()
        if global_latest is None or int(global_latest.id) != int(upload.id):
            raise SystemExit("RECOVERY_REFUSED|reason=upload_is_not_global_latest")

        target_count = Target.query.filter_by(year=args.year, month=args.month).count()
        if target_count:
            raise SystemExit(f"RECOVERY_REFUSED|reason=targets_not_empty|targets={target_count}")

        job = (
            IMSImportJob.query.filter_by(
                ims_upload_id=upload.id,
                status=IMSImportJob.STATUS_COMPLETED,
            )
            .order_by(IMSImportJob.completed_at.desc(), IMSImportJob.id.desc())
            .first()
        )
        if job is None:
            raise SystemExit("RECOVERY_REFUSED|reason=completed_job_not_found")

        source = IMSUploadLifecycleService._validate_archived_source(upload.id)
        staging = Path(app.config["UPLOAD_FOLDER"]) / "ims_queue" / job.stored_file_name
        staging.parent.mkdir(parents=True, exist_ok=True)
        temporary = staging.with_suffix(staging.suffix + ".recovery")
        shutil.copy2(source, temporary)
        if IMSUploadLifecycleService._file_sha256(temporary) != str(job.source_hash).strip().lower():
            temporary.unlink(missing_ok=True)
            raise SystemExit("RECOVERY_REFUSED|reason=staging_hash_mismatch")

        now = datetime.utcnow()
        try:
            temporary.replace(staging)
            upload = db.session.get(IMSUpload, upload.id)
            job = db.session.get(IMSImportJob, job.id)
            upload.status = "PROCESSING"
            upload.error_message = None
            upload.warning_message = None
            upload.reconciliation_status = "NOT_AVAILABLE"
            upload.completed_at = None
            job.status = IMSImportJob.STATUS_QUEUED
            job.clear_before_import = True
            job.started_at = None
            job.completed_at = None
            job.heartbeat_at = None
            job.error_message = None
            job.result_summary = None
            job.queued_at = now
            db.session.commit()
        except Exception:
            db.session.rollback()
            staging.unlink(missing_ok=True)
            raise

        print(
            "IMS_NORMAL_REIMPORT_QUEUED|"
            f"upload={upload.id}|job={job.id}|period={args.year:04d}-{args.month:02d}|"
            f"week={args.week}|clear_before_import=1|source=verified_archive"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
