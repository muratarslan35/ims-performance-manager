"""Requeue the latest empty-target IMS through the normal worker.

The exact archived workbook and original queue identity are reused. A previous
COMPLETED or FAILED attempt is eligible, but only when it is still the newest
IMS upload, no import is active, and the period still has zero targets. The
regular worker remains the only component that performs replacement import and
snapshot/publication.
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
            IMSUpload.query.filter_by(year=args.year, month=args.month, week_number=args.week)
            .filter(IMSUpload.status.in_((IMSUpload.STATUS_COMPLETED, "FAILED")))
            .order_by(IMSUpload.id.desc())
            .first()
        )
        if upload is None:
            raise SystemExit("RECOVERY_REFUSED|reason=retryable_upload_not_found")

        global_latest = IMSUpload.query.order_by(
            IMSUpload.year.desc(), IMSUpload.month.desc(), IMSUpload.week_number.desc(), IMSUpload.id.desc()
        ).first()
        if global_latest is None or int(global_latest.id) != int(upload.id):
            raise SystemExit("RECOVERY_REFUSED|reason=upload_is_not_global_latest")

        target_count = Target.query.filter_by(year=args.year, month=args.month).count()
        if target_count:
            raise SystemExit(f"RECOVERY_REFUSED|reason=targets_not_empty|targets={target_count}")

        job = (
            IMSImportJob.query.filter_by(ims_upload_id=upload.id)
            .filter(IMSImportJob.status.in_((IMSImportJob.STATUS_COMPLETED, IMSImportJob.STATUS_FAILED)))
            .order_by(IMSImportJob.id.desc())
            .first()
        )
        if job is None:
            raise SystemExit("RECOVERY_REFUSED|reason=retryable_job_not_found")

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
