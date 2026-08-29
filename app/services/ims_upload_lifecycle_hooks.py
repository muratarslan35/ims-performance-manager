"""Install rollback-snapshot and source-archive hooks around queued IMS imports."""
from __future__ import annotations

import logging
from pathlib import Path

from flask import current_app

from app.extensions import db
from app.models import IMSImportJob
from app.services.ims_import_queue import IMSImportQueue
from app.services.ims_upload_lifecycle_service import IMSUploadLifecycleService


logger = logging.getLogger(__name__)


def install_ims_upload_lifecycle() -> None:
    if getattr(IMSImportQueue, "_upload_lifecycle_installed", False):
        return

    original_process = IMSImportQueue.process

    @classmethod
    def process_with_upload_lifecycle(cls, job):
        staging_path = Path(current_app.config["UPLOAD_FOLDER"]) / "ims_queue" / job.stored_file_name
        pending_source = IMSUploadLifecycleService._archive_root() / f"pending-job-{int(job.id)}{staging_path.suffix.lower()}"
        snapshot_captured = False

        try:
            try:
                IMSUploadLifecycleService.capture_period_snapshot(
                    job_id=job.id,
                    year=job.year,
                    month=job.month,
                )
                snapshot_captured = True
            except Exception:
                logger.exception("ims_lifecycle_snapshot_capture_failed job_id=%s", job.id)

            try:
                if staging_path.is_file():
                    pending_source.write_bytes(staging_path.read_bytes())
            except Exception:
                logger.exception("ims_lifecycle_source_staging_failed job_id=%s", job.id)
                pending_source.unlink(missing_ok=True)

            result = original_process(job)
            db.session.expire_all()
            refreshed = db.session.get(IMSImportJob, int(job.id))

            if refreshed is not None and refreshed.status == IMSImportJob.STATUS_COMPLETED and refreshed.ims_upload_id:
                if snapshot_captured:
                    IMSUploadLifecycleService.finalize_snapshot(
                        job_id=refreshed.id,
                        upload_id=refreshed.ims_upload_id,
                    )
                if pending_source.is_file():
                    try:
                        IMSUploadLifecycleService.archive_successful_source(
                            staging_path=pending_source,
                            upload_id=refreshed.ims_upload_id,
                        )
                    except Exception:
                        logger.exception(
                            "ims_lifecycle_source_archive_failed job_id=%s upload_id=%s",
                            refreshed.id,
                            refreshed.ims_upload_id,
                        )
            else:
                IMSUploadLifecycleService.discard_pending_snapshot(job.id)
            return result
        finally:
            pending_source.unlink(missing_ok=True)
            # A failed/cancelled import must never leave a rollback marker that
            # could later be mistaken for an authoritative previous state.
            refreshed = db.session.get(IMSImportJob, int(job.id))
            if refreshed is None or refreshed.status != IMSImportJob.STATUS_COMPLETED:
                IMSUploadLifecycleService.discard_pending_snapshot(job.id)

    IMSImportQueue.process = process_with_upload_lifecycle
    IMSImportQueue._upload_lifecycle_installed = True
