from datetime import datetime
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

import pytest
from flask_migrate import upgrade

from app import create_app
from app.extensions import db
from app.models import IMSImportJob, IMSUpload
from app.services import ims_import_service as ims_import_service_module
from app.services.compiled_competition_import_service import CompiledCompetitionImportService
from app.services.competition_import_service import CompetitionImportService
from app.services.ims_import_queue import IMSImportQueue


@pytest.fixture()
def app(tmp_path):
    config = type(
        "QueueTestConfig",
        (),
        {
            "TESTING": True,
            "SECRET_KEY": "queue-test",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'queue.db'}",
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "UPLOAD_FOLDER": tmp_path / "uploads",
            "REPORT_FOLDER": tmp_path / "reports",
            "BACKUP_FOLDER": tmp_path / "backups",
            "LOG_FOLDER": tmp_path / "logs",
        },
    )
    application = create_app(config)
    with application.app_context():
        upgrade(directory=str(Path(__file__).resolve().parents[1] / "migrations"))
    return application


def _job(name="queued.xlsx", status=IMSImportJob.STATUS_QUEUED, stored_file_name=None):
    item = IMSImportJob(
        status=status,
        file_name=name,
        stored_file_name=stored_file_name or f"stored-{name}",
        source_hash="a" * 64,
        year=2026,
        month=2,
        uploaded_by="Queue Tester",
        heartbeat_at=datetime.utcnow(),
    )
    db.session.add(item)
    db.session.commit()
    return item


def test_claim_is_single_use(app):
    with app.app_context():
        queued = _job()
        claimed = IMSImportQueue.claim_next()
        assert claimed.id == queued.id
        assert claimed.status == IMSImportJob.STATUS_PROCESSING
        assert IMSImportQueue.claim_next() is None


def test_recover_processing_job_as_failed(app):
    with app.app_context():
        processing = _job(status=IMSImportJob.STATUS_PROCESSING)
        assert IMSImportQueue.recover_stale() == 1
        db.session.refresh(processing)
        assert processing.status == IMSImportJob.STATUS_FAILED
        assert "canlı veriler korunmuştur" in processing.error_message


def test_worker_completes_job_and_links_business_upload(app):
    with app.app_context():
        job = _job(status=IMSImportJob.STATUS_PROCESSING)
        staging = Path(app.config["UPLOAD_FOLDER"]) / "ims_queue" / job.stored_file_name
        staging.parent.mkdir(parents=True, exist_ok=True)
        staging.write_bytes(b"workbook")
        observed = {}
        original_chunk_size = CompetitionImportService.BULK_CHUNK_SIZE
        original_service = ims_import_service_module.CompetitionImportService

        def fake_run(**kwargs):
            observed["competition_service"] = ims_import_service_module.CompetitionImportService
            observed["chunk_size"] = CompetitionImportService.BULK_CHUNK_SIZE
            observed["run_kwargs"] = kwargs
            upload = IMSUpload(file_name=job.stored_file_name, year=2026, month=2, status="COMPLETED")
            db.session.add(upload)
            db.session.commit()
            return {"success": True, "upload_id": upload.id, "statistics": {}, "warnings": []}

        with mock.patch("app.services.ims_import_queue.ImportCoordinator.acquire", return_value=nullcontext()), \
             mock.patch("app.services.ims_import_queue.IMSImportService.run", side_effect=fake_run), \
             mock.patch("app.services.ims_import_queue.OfficialBrickSpreadService.persist", return_value={"records": 0, "representatives": 0}):
            IMSImportQueue.process(job)

        db.session.refresh(job)
        upload = db.session.get(IMSUpload, job.ims_upload_id)
        assert job.status == IMSImportJob.STATUS_COMPLETED
        assert job.ims_upload_id is not None
        assert not staging.exists()
        assert observed["competition_service"] is CompiledCompetitionImportService
        assert observed["chunk_size"] == 25000
        assert observed["run_kwargs"]["week_number"] is None
        assert upload.file_name == job.file_name
        assert ims_import_service_module.CompetitionImportService is original_service
        assert CompetitionImportService.BULK_CHUNK_SIZE == original_chunk_size
        assert '"competition_compiled_fast_path": true' in job.result_summary


def test_worker_preserves_week_from_original_name_not_uuid_staging_name(app):
    with app.app_context():
        job = _job(
            "Tayfun 7.Hafta Şubat Brick Analizi_.xlsx",
            status=IMSImportJob.STATUS_PROCESSING,
            stored_file_name="2026-02-4129e872742e4301b56ae1ab6ff85cd7.xlsx",
        )
        staging = Path(app.config["UPLOAD_FOLDER"]) / "ims_queue" / job.stored_file_name
        staging.parent.mkdir(parents=True, exist_ok=True)
        staging.write_bytes(b"workbook")
        observed = {}

        def fake_run(**kwargs):
            observed.update(kwargs)
            upload = IMSUpload(file_name=job.stored_file_name, year=2026, month=2, status="COMPLETED")
            db.session.add(upload)
            db.session.commit()
            return {"success": True, "upload_id": upload.id, "statistics": {}, "warnings": []}

        with mock.patch("app.services.ims_import_queue.ImportCoordinator.acquire", return_value=nullcontext()), \
             mock.patch("app.services.ims_import_queue.IMSImportService.run", side_effect=fake_run), \
             mock.patch("app.services.ims_import_queue.OfficialBrickSpreadService.persist", return_value={"records": 0, "representatives": 0}):
            IMSImportQueue.process(job)

        db.session.refresh(job)
        upload = db.session.get(IMSUpload, job.ims_upload_id)
        summary = __import__("json").loads(job.result_summary)
        assert observed["year"] == 2026
        assert observed["month"] == 2
        assert observed["week_number"] == 7
        assert observed["clear_before_import"] is False
        assert summary["detected_week_number"] == 7
        assert upload.file_name == job.file_name


def test_worker_failure_marks_job_without_business_upload(app):
    with app.app_context():
        job = _job("failed.xlsx", status=IMSImportJob.STATUS_PROCESSING)
        staging = Path(app.config["UPLOAD_FOLDER"]) / "ims_queue" / job.stored_file_name
        staging.parent.mkdir(parents=True, exist_ok=True)
        staging.write_bytes(b"workbook")
        original_chunk_size = CompetitionImportService.BULK_CHUNK_SIZE
        original_service = ims_import_service_module.CompetitionImportService
        with mock.patch("app.services.ims_import_queue.ImportCoordinator.acquire", return_value=nullcontext()), \
             mock.patch("app.services.ims_import_queue.IMSImportService.run", side_effect=RuntimeError("invalid workbook")):
            IMSImportQueue.process(job)
        db.session.refresh(job)
        assert job.status == IMSImportJob.STATUS_FAILED
        assert IMSUpload.query.count() == 0
        assert ims_import_service_module.CompetitionImportService is original_service
        assert CompetitionImportService.BULK_CHUNK_SIZE == original_chunk_size
