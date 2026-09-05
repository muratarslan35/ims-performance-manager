"""Persistent, single-consumer IMS import queue."""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from flask import current_app
from sqlalchemy import update

from app.extensions import db
from app.models import IMSImportJob, IMSUpload
from app.services import ims_import_service as ims_import_service_module
from app.services.alias_service import AliasService
from app.services.compiled_competition_import_service import CompiledCompetitionImportService
from app.services.competition_import_service import CompetitionImportService
from app.services.import_coordinator import ImportCoordinator
from app.services.ims_import_service import IMSImportService
from app.services.ims_progress_store import IMSProgressStore
from app.services.official_brick_spread_service import OfficialBrickSpreadService
from app.services.persistent_region_snapshot_service import PersistentRegionSnapshotService


_PROGRESS_STAGES = {
    "validate_and_load_workbook": (5, 15, "Dosya kontrol ediliyor", "Dosya kontrol edildi"),
    "discover_and_prepare_sheets": (15, 25, "Sayfalar okunuyor", "Sayfalar okundu"),
    "stage_raw_rows": (25, 35, "Temsilciler ve bölgeler eşleştiriliyor", "Temsilciler ve bölgeler alındı"),
    "assignments_and_targets": (35, 45, "Hedefler okunuyor", "Hedefler okundu"),
    "facts_summary_and_official_aggregates": (45, 60, "Ürün çıkışları okunuyor", "Ürün çıkışları okundu"),
    "competition_import": (60, 90, "Rekabet verileri okunuyor", "Rekabet verileri okundu"),
    "source_reconciliation": (90, 96, "Veriler karşılaştırılıyor ve doğrulanıyor", "Veriler karşılaştırıldı ve doğrulandı"),
    "commit_upload": (97, 99, "Son kayıtlar tamamlanıyor", "Son kayıtlar tamamlandı"),
}


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
        job = db.session.get(IMSImportJob, candidate.id)
        IMSProgressStore.write(
            job.id,
            percent=5,
            stage="processing",
            message="Dosya kontrol ediliyor",
            detail=job.file_name,
            status=IMSImportJob.STATUS_PROCESSING,
        )
        return job

    @classmethod
    def recover_stale(cls):
        jobs = IMSImportJob.query.filter(
            IMSImportJob.status == IMSImportJob.STATUS_PROCESSING,
        ).all()
        for job in jobs:
            job.status = IMSImportJob.STATUS_FAILED
            job.completed_at = datetime.utcnow()
            job.error_message = "IMS worker beklenmedik biçimde durdu; canlı veriler korunmuştur."
            IMSProgressStore.write(
                job.id,
                percent=100,
                stage="failed",
                message="IMS yüklemesi tamamlanamadı",
                detail="Mevcut veriler korunmuştur",
                status=IMSImportJob.STATUS_FAILED,
            )
        if jobs:
            db.session.commit()
        return len(jobs)

    @classmethod
    def process(cls, job):
        staging_path = Path(current_app.config["UPLOAD_FOLDER"]) / "ims_queue" / job.stored_file_name
        previous_chunk_size = CompetitionImportService.BULK_CHUNK_SIZE
        previous_competition_service = ims_import_service_module.CompetitionImportService
        previous_compiled_sheet_import = CompiledCompetitionImportService._import_compiled_sheet

        def set_progress(percent, stage, message, detail=None, status=IMSImportJob.STATUS_PROCESSING):
            IMSProgressStore.write(
                job.id,
                percent=percent,
                stage=stage,
                message=message,
                detail=detail,
                status=status,
            )

        try:
            with ImportCoordinator.acquire(
                uploaded_by=job.uploaded_by,
                file_name=job.file_name,
                wait_seconds=current_app.config.get("IMS_IMPORT_LOCK_WAIT_SECONDS", 2),
            ):
                detected_week_number = IMSImportService.extract_week_number(job.file_name)
                ims_import_service_module.CompetitionImportService = CompiledCompetitionImportService

                configured_chunk = int(current_app.config.get("IMS_COMPETITION_BULK_CHUNK_SIZE", 25000) or 25000)
                CompetitionImportService.BULK_CHUNK_SIZE = max(1000, min(configured_chunk, 25000))
                effective_chunk_size = CompetitionImportService.BULK_CHUNK_SIZE

                # Competition is the longest stage.  Advance the visible bar
                # after each real competition sheet finishes; no timer or random
                # percentage is used.
                def progress_compiled_sheet(service, structure_info, sheet_name):
                    total = max(len(service.get_supported_sheets()), 1)
                    completed = int(getattr(service, "_ui_completed_competition_sheets", 0))
                    start_percent = 60 + round(30 * completed / total)
                    set_progress(
                        start_percent,
                        "competition",
                        "Rekabet verileri okunuyor",
                        f"{completed + 1}/{total} rekabet sayfası",
                    )
                    result = previous_compiled_sheet_import(service, structure_info, sheet_name)
                    completed += 1
                    service._ui_completed_competition_sheets = completed
                    end_percent = 60 + round(30 * completed / total)
                    set_progress(
                        min(end_percent, 90),
                        "competition",
                        "Rekabet verileri okundu" if completed == total else "Rekabet verileri okunuyor",
                        f"{completed}/{total} rekabet sayfası tamamlandı",
                    )
                    return result

                CompiledCompetitionImportService._import_compiled_sheet = progress_compiled_sheet

                job.heartbeat_at = datetime.utcnow()
                db.session.commit()

                # AliasService intentionally uses process-wide lookup caches for
                # performance. Those caches contain ORM objects, however, so a
                # successful job leaves objects associated with the previous
                # SQLAlchemy session. The next queued workbook must never reuse
                # those detached Product/Representative instances.
                AliasService.clear_cache()
                service = IMSImportService(str(staging_path), uploaded_by=job.uploaded_by)
                original_measure_stage = service._measure_stage

                @contextmanager
                def progress_measure_stage(stage):
                    progress = _PROGRESS_STAGES.get(stage)
                    if progress:
                        start_percent, _, start_message, _ = progress
                        set_progress(start_percent, stage, start_message, job.file_name if stage == "validate_and_load_workbook" else None)
                    succeeded = False
                    try:
                        with original_measure_stage(stage):
                            yield
                        succeeded = True
                    finally:
                        if succeeded and progress:
                            _, end_percent, _, end_message = progress
                            set_progress(end_percent, stage, end_message)

                service._measure_stage = progress_measure_stage

                with db.session.no_autoflush:
                    result = service.run(
                        year=job.year,
                        month=job.month,
                        clear_before_import=job.clear_before_import,
                        week_number=detected_week_number,
                    )
                if not result.get("success"):
                    raise RuntimeError("; ".join(result.get("errors") or ["IMS doğrulaması başarısız."]))

                set_progress(99, "final_checks", "Son kontroller tamamlanıyor")
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
                    upload.file_name = job.file_name
                    upload.warning_message = "\n".join(warnings) or None

                # Finalize the IMS source first, then build the read-only region
                # set without holding the import write transaction. The worker is
                # already a single consumer, so this adds no concurrent DB storm.
                db.session.commit()
                snapshot_result = {"status": "NOT_BUILT", "regions": 0}
                try:
                    set_progress(
                        99,
                        "region_snapshots",
                        "Bölge analizleri hazırlanıyor",
                        "Yeni IMS için kalıcı snapshot seti oluşturuluyor",
                    )

                    def snapshot_progress(done, total, region_name):
                        current_job = db.session.get(IMSImportJob, job.id)
                        if current_job is not None:
                            current_job.heartbeat_at = datetime.utcnow()
                            db.session.commit()
                        set_progress(
                            99,
                            "region_snapshots",
                            "Bölge analizleri hazırlanıyor",
                            f"{done}/{total} · {region_name}",
                        )

                    snapshot_result = PersistentRegionSnapshotService.build_for_period(
                        job.year,
                        job.month,
                        progress=snapshot_progress,
                    )
                except Exception as snapshot_exc:
                    # Snapshot acceleration must never turn a valid IMS import
                    # into a failed business-data import. The previous ACTIVE set
                    # remains intact and runtime calculation is the safe fallback.
                    current_app.logger.exception(
                        "region_snapshot_build_failed upload_id=%s",
                        result["upload_id"],
                    )
                    snapshot_result = {
                        "status": "FAILED",
                        "regions": 0,
                        "error": str(snapshot_exc)[:500],
                    }

                completed_at = datetime.utcnow()
                stats = dict(result.get("statistics") or {})
                stats["competition_bulk_chunk_size"] = effective_chunk_size
                stats["competition_compiled_fast_path"] = True
                stats["detected_week_number"] = detected_week_number
                stats["official_brick_spread_records"] = spread["records"]
                stats["official_brick_spread_representatives"] = spread["representatives"]
                stats["manager_region_snapshot_status"] = snapshot_result.get("status")
                stats["manager_region_snapshot_regions"] = snapshot_result.get("regions", 0)
                stats["background_job_seconds"] = (
                    round((completed_at - job.started_at).total_seconds(), 3)
                    if job.started_at is not None
                    else None
                )
                job = db.session.get(IMSImportJob, job.id)
                job.ims_upload_id = result["upload_id"]
                job.status = IMSImportJob.STATUS_COMPLETED
                job.result_summary = json.dumps(stats, ensure_ascii=False, default=str)
                job.error_message = None
                job.completed_at = completed_at
                job.heartbeat_at = completed_at
                db.session.commit()
                set_progress(
                    100,
                    "completed",
                    "IMS yüklemesi başarıyla tamamlandı",
                    f"{detected_week_number}. hafta" if detected_week_number else None,
                    status=IMSImportJob.STATUS_COMPLETED,
                )
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("ims_background_import_failed job_id=%s", job.id)
            failed = db.session.get(IMSImportJob, job.id)
            failed.status = IMSImportJob.STATUS_FAILED
            failed.error_message = str(exc)[:4000]
            failed.completed_at = datetime.utcnow()
            failed.heartbeat_at = failed.completed_at
            db.session.commit()
            set_progress(
                100,
                "failed",
                "IMS yüklemesi tamamlanamadı",
                "Mevcut veriler korunmuştur",
                status=IMSImportJob.STATUS_FAILED,
            )
        finally:
            # Drop ORM-backed lookup caches after every success/failure so the
            # long-lived worker never carries session-bound objects into the
            # next queued import.
            AliasService.clear_cache()
            CompiledCompetitionImportService._import_compiled_sheet = previous_compiled_sheet_import
            ims_import_service_module.CompetitionImportService = previous_competition_service
            CompetitionImportService.BULK_CHUNK_SIZE = previous_chunk_size
            staging_path.unlink(missing_ok=True)
