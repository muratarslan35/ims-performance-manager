"""Requeue the latest IMS through the normal worker.

The exact archived workbook and original queue identity are reused. By default
this remains the empty-target recovery path. An explicit
--allow-existing-targets flag permits an operator-approved replacement reimport
of the newest period while preserving all other safety gates. The regular
worker remains the only component that performs replacement import and
snapshot/publication.
"""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa

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
    parser.add_argument(
        "--allow-existing-targets",
        action="store_true",
        help="Explicitly allow replacement reimport when the selected period already has targets.",
    )
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
        if target_count and not args.allow_existing_targets:
            raise SystemExit(f"RECOVERY_REFUSED|reason=targets_not_empty|targets={target_count}")

        job = (
            IMSImportJob.query.filter_by(ims_upload_id=upload.id)
            .filter(IMSImportJob.status.in_((IMSImportJob.STATUS_COMPLETED, IMSImportJob.STATUS_FAILED)))
            .order_by(IMSImportJob.id.desc())
            .first()
        )
        if job is None or not str(job.source_hash or "").strip():
            raise SystemExit("RECOVERY_REFUSED|reason=retryable_job_hash_not_found")

        source = IMSUploadLifecycleService.archived_source_for_upload(upload.id)
        if source is None:
            raise SystemExit("RECOVERY_REFUSED|reason=archived_source_not_found")
        expected_hash = str(job.source_hash).strip().lower()
        if IMSUploadLifecycleService._file_sha256(source) != expected_hash:
            raise SystemExit("RECOVERY_REFUSED|reason=archived_source_hash_mismatch")

        upload_id = int(upload.id)
        job_id = int(job.id)
        stored_file_name = str(job.stored_file_name)
        staging = Path(app.config["UPLOAD_FOLDER"]) / "ims_queue" / stored_file_name
        staging.parent.mkdir(parents=True, exist_ok=True)
        temporary = staging.with_suffix(staging.suffix + ".recovery")
        shutil.copy2(source, temporary)
        if IMSUploadLifecycleService._file_sha256(temporary) != expected_hash:
            temporary.unlink(missing_ok=True)
            raise SystemExit("RECOVERY_REFUSED|reason=staging_hash_mismatch")

        # All safety checks above are reads. End that transaction before the
        # queue handoff so SQLite does not have to upgrade a long-lived read
        # snapshot to a writer after the archive copy. Reload both rows in one
        # fresh, short write transaction.
        db.session.rollback()

        now = datetime.utcnow()
        try:
            temporary.replace(staging)
            # Acquire SQLite's single writer slot before re-reading the queue
            # rows. A deferred SELECT transaction cannot be safely upgraded if
            # another connection changes the WAL generation between read and
            # flush; BEGIN IMMEDIATE makes this handoff deterministic.
            db.session.execute(sa.text("BEGIN IMMEDIATE"))
            upload = db.session.get(IMSUpload, upload_id)
            job = db.session.get(IMSImportJob, job_id)
            if upload is None or job is None:
                raise RuntimeError("RECOVERY_REFUSED|reason=queue_rows_disappeared")
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
            f"week={args.week}|clear_before_import=1|source=verified_archive|"
            f"existing_targets={target_count}|explicit_replace={int(args.allow_existing_targets)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
