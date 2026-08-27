"""Persistent, single-consumer IMS import queue."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from flask import current_app
from sqlalchemy import update

from app.extensions import db
from app.models import IMSImportJob, IMSUpload
from app.services import ims_import_service as ims_import_service_module
from app.services.compiled_competition_import_service import CompiledCompetitionImportService
from app.services.competition_import_service import CompetitionImportService
from app.services.import_coordinator import ImportCoordinator
from app.services.ims_import_service import IMSImportService
from app.services.official_brick_spread_service import OfficialBrickSpreadService


class IMSImportQueue:
    @classmethod
    def claim_next(cls):
        candidate = (
            db.session.query(IMSImportJob.id)
            .filter(IMSImportJob.status == IMSImportJob.STATUS_QUEUED)
            .order_by(IMSImportJob.queued_at, IMSImportJob.id)
            .first()
        )
        if candidate is None:
            return None
        now = datetime.utcnow()
        claimed = db.session.execute(
            update(IMSImportJob)
            .where(
                IMSImportJob.id == candidate.id,
                IMSImportJob.status == IMSImportJob.STATUS_QUEUED,
            )
            .values(status=IMSImportJob.STATUS_PROCESSING, started_at=now, heartbeat_at=now)
        )
        db.session.commit()
        if claimed.rowcount != 1:
            return None
        return db.session.get(IMSImportJob, candidate.id)

    @classmethod
    def recover_stale(cls):
        jobs = IMSImportJob.query.filter(
            IMSImportJob.status == IMSImportJob.STATUS_PROCESSING,
        ).all()
        for job in jobs:
            job.status = IMSImportJob.STATUS_FAILED
            job.completed_at = datetime.utcnow()
            job.error_message = "IMS worker beklenmedik biçimde durdu; canlı veriler korunmuştur."
        if jobs:
            db.session.commit()
        return len(jobs)

    @classmethod
    def process(cls, job):
        staging_path = Path(current_app.config["UPLOAD_FOLDER"]) / "ims_queue" / job.stored_file_name
        previous_chunk_size = CompetitionImportService.BULK_CHUNK_SIZE
        previous_competition_service = ims_import_service_module.CompetitionImportService
        try:
            with ImportCoordinator.acquire(
                uploaded_by=job.uploaded_by,
                file_name=job.file_name,
                wait_seconds=current_app.config.get("IMS_IMPORT_LOCK_WAIT_SECONDS", 2),
            ):
                # The worker is the only production writer. Semantic discovery
                # remains in the established importer, while the already-
                # resolved competition plan is executed by the compiled hot
                # loop to avoid per-cell re-normalization/allocation overhead.
                ims_import_service_module.CompetitionImportService = CompiledCompetitionImportService

                # Competition is the dominant write volume. 25k remains bounded
                # on the 1 GB host but reduces a 467k-row workbook to ~19 DB
                # executemany batches. Restore the process-wide default after
                # every job so non-worker call sites keep legacy behavior.
                configured_chunk = int(current_app.config.get("IMS_COMPETITION_BULK_CHUNK_SIZE", 25000) or 25000)
                CompetitionImportService.BULK_CHUNK_SIZE = max(1000, min(configured_chunk, 25000))
                effective_chunk_size = CompetitionImportService.BULK_CHUNK_SIZE

                job.heartbeat_at = datetime.utcnow()
                db.session.commit()
                with db.session.no_autoflush:
                    result = IMSImportService(str(staging_path), uploaded_by=job.uploaded_by).run(
                        year=job.year,
                        month=job.month,
                        clear_before_import=job.clear_before_import,
                    )
                if not result.get("success"):
                    raise RuntimeError("; ".join(result.get("errors") or ["IMS doğrulaması başarısız."]))
                spread = OfficialBrickSpreadService.persist(
                    file_path=staging_path,
                    upload_id=result["upload_id"],
                    year=job.year,
                    month=job.month,
                )
                warnings = [
                    item for item in result.get("warnings", [])
                    if "SATIS BRICK YAYILIMI" not in OfficialBrickSpreadService._normalize(item)
                ]
                upload = db.session.get(IMSUpload, result["upload_id"])
                if upload is not None:
                    upload.warning_message = "\n".join(warnings) or None
                stats = dict(result.get("statistics") or {})
                stats["competition_bulk_chunk_size"] = effective_chunk_size
                stats["competition_compiled_fast_path"] = True
                stats["official_brick_spread_records"] = spread["records"]
                stats["official_brick_spread_representatives"] = spread["representatives"]
                job.ims_upload_id = result["upload_id"]
                job.status = IMSImportJob.STATUS_COMPLETED
                job.result_summary = json.dumps(stats, ensure_ascii=False, default=str)
                job.error_message = None
                job.completed_at = datetime.utcnow()
                job.heartbeat_at = job.completed_at
                db.session.commit()
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("ims_background_import_failed job_id=%s", job.id)
            failed = db.session.get(IMSImportJob, job.id)
            failed.status = IMSImportJob.STATUS_FAILED
            failed.error_message = str(exc)[:4000]
            failed.completed_at = datetime.utcnow()
            failed.heartbeat_at = failed.completed_at
            db.session.commit()
        finally:
            ims_import_service_module.CompetitionImportService = previous_competition_service
            CompetitionImportService.BULK_CHUNK_SIZE = previous_chunk_size
            staging_path.unlink(missing_ok=True)
