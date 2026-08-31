"""Install rollback, archive and semantic-duplicate hooks around queued IMS imports."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from flask import current_app, has_request_context, request

from app.extensions import db
from app.models import IMSImportJob
from app.services.import_roster_sync import IMSRosterSyncService
from app.services.ims_import_queue import IMSImportQueue
from app.services.ims_import_service import IMSImportService
from app.services.ims_progress_store import IMSProgressStore
from app.services.ims_upload_lifecycle_service import IMSUploadLifecycleService


logger = logging.getLogger(__name__)


def install_ims_upload_lifecycle() -> None:
    if getattr(IMSImportQueue, "_upload_lifecycle_installed", False):
        return

    original_process = IMSImportQueue.process
    original_exact_duplicate_job = IMSUploadLifecycleService.exact_duplicate_job

    @classmethod
    def exact_duplicate_job_with_explicit_replace(cls, source_hash):
        if has_request_context() and request.form.get("replace") == "1":
            return None
        return original_exact_duplicate_job(source_hash)

    IMSUploadLifecycleService.exact_duplicate_job = exact_duplicate_job_with_explicit_replace

    @classmethod
    def process_with_upload_lifecycle(cls, job):
        staging_path = Path(current_app.config["UPLOAD_FOLDER"]) / "ims_queue" / job.stored_file_name
        archive_root = IMSUploadLifecycleService._archive_root()
        suffix = staging_path.suffix.lower() if staging_path.suffix.lower() in {".xlsx", ".xls"} else ".xlsx"
        pending_source = archive_root / f"pending-job-{int(job.id)}{suffix}"
        failed_source = archive_root / f"failed-job-{int(job.id)}{suffix}"
        snapshot_captured = False

        try:
            detected_week = IMSImportService.extract_week_number(job.file_name)
            existing_week = IMSUploadLifecycleService.existing_week_job(
                year=job.year,
                month=job.month,
                week_number=detected_week,
            )
            if not bool(job.clear_before_import) and existing_week is not None and existing_week.ims_upload_id:
                same_semantic = IMSUploadLifecycleService.same_semantic_workbook(
                    staging_path,
                    existing_week.ims_upload_id,
                )
                if same_semantic is True:
                    completed_at = datetime.utcnow()
                    duplicate = db.session.get(IMSImportJob, int(job.id))
                    duplicate.status = IMSImportJob.STATUS_FAILED
                    duplicate.error_message = (
                        "Bu IMS dosyasındaki tüm hücre verileri sistemdeki aynı hafta IMS ile aynıdır; "
                        "dosya zaten yüklü olduğu için tekrar import edilmedi."
                    )
                    duplicate.completed_at = completed_at
                    duplicate.heartbeat_at = completed_at
                    db.session.commit()
                    IMSProgressStore.write(
                        duplicate.id,
                        percent=100,
                        stage="duplicate",
                        message="Bu IMS zaten yüklü",
                        detail=f"{detected_week}. hafta verileri birebir aynı" if detected_week else "Veriler birebir aynı",
                        status=IMSImportJob.STATUS_FAILED,
                    )
                    return None

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
                        failed_source.unlink(missing_ok=True)
                    except Exception:
                        logger.exception(
                            "ims_lifecycle_source_archive_failed job_id=%s upload_id=%s",
                            refreshed.id,
                            refreshed.ims_upload_id,
                        )
                try:
                    roster_result = IMSRosterSyncService.sync_latest()
                    logger.info("ims_roster_sync_success %s", roster_result)
                except Exception:
                    db.session.rollback()
                    logger.exception(
                        "ims_roster_sync_failed job_id=%s upload_id=%s",
                        refreshed.id,
                        refreshed.ims_upload_id,
                    )
            else:
                IMSUploadLifecycleService.discard_pending_snapshot(job.id)
                if pending_source.is_file():
                    try:
                        pending_source.replace(failed_source)
                        logger.info("ims_failed_source_preserved job_id=%s path=%s", job.id, failed_source.name)
                    except Exception:
                        logger.exception("ims_failed_source_preserve_failed job_id=%s", job.id)
            return result
        finally:
            pending_source.unlink(missing_ok=True)
            staging_path.unlink(missing_ok=True)
            refreshed = db.session.get(IMSImportJob, int(job.id))
            if refreshed is None or refreshed.status != IMSImportJob.STATUS_COMPLETED:
                IMSUploadLifecycleService.discard_pending_snapshot(job.id)

    IMSImportQueue.process = process_with_upload_lifecycle
    IMSImportQueue._upload_lifecycle_installed = True
