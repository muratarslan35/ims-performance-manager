from pathlib import Path
import tempfile

from app import create_app
from app.extensions import db
from app.models import (
    IMSFact,
    IMSImportJob,
    IMSRawData,
    IMSSummary,
    IMSUpload,
    Product,
    Representative,
    RepresentativeBrickAssignment,
    Setting,
    Target,
)
from app.services.ims_upload_lifecycle_service import IMSUploadLifecycleService


class LifecycleConfig:
    TESTING = True
    SECRET_KEY = "ims-lifecycle-test"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = Path(tempfile.gettempdir()) / "ims-lifecycle-uploads"
    REPORT_FOLDER = Path(tempfile.gettempdir()) / "ims-lifecycle-reports"
    BACKUP_FOLDER = Path(tempfile.gettempdir()) / "ims-lifecycle-backups"
    LOG_FOLDER = Path(tempfile.gettempdir()) / "ims-lifecycle-logs"


def _context():
    app = create_app(LifecycleConfig)
    ctx = app.app_context()
    ctx.push()
    db.create_all()
    return app, ctx


def _seed_period():
    rep = Representative(rep_code="LC-REP", rep_name="LIFECYCLE REP", active=True)
    product = Product(product_code="LC-PROD", product_name="Lifecycle Product", is_active=True)
    previous = IMSUpload(
        file_name="7.Hafta.xlsx", year=2033, month=2, quarter="Q1", week_number=7,
        status="COMPLETED", reconciliation_status="PASSED",
    )
    db.session.add_all([rep, product, previous])
    db.session.flush()
    target = Target(
        year=2033, month=2, quarter="Q1", representative_id=rep.id, product_id=product.id,
        unit_target=1000.0, tl_target=10000.0, unit_realization=700.0, tl_realization=7000.0,
    )
    summary = IMSSummary(
        upload_id=previous.id, year=2033, month=2, quarter="Q1",
        representative_id=rep.id, product_id=product.id,
        unit=700.0, tl=7000.0, target_unit=1000.0, target_tl=10000.0,
    )
    assignment = RepresentativeBrickAssignment(
        representative_id=rep.id, year=2033, month=2, quarter="Q1",
        brick="901 TEST", source="IMS", active=True,
    )
    db.session.add_all([target, summary, assignment])
    db.session.flush()
    return rep, product, previous, target, summary


def test_exact_duplicate_completed_job_is_detected():
    app, ctx = _context()
    try:
        upload = IMSUpload(
            file_name="8.Hafta.xlsx", year=2033, month=2, week_number=8,
            status="COMPLETED", reconciliation_status="PASSED",
        )
        db.session.add(upload)
        db.session.flush()
        job = IMSImportJob(
            status=IMSImportJob.STATUS_COMPLETED,
            file_name=upload.file_name,
            stored_file_name="stored.xlsx",
            source_hash="a" * 64,
            year=2033,
            month=2,
            clear_before_import=True,
            uploaded_by="Manager",
            ims_upload_id=upload.id,
        )
        db.session.add(job)
        db.session.commit()
        assert IMSUploadLifecycleService.exact_duplicate_job("a" * 64).id == job.id
        assert IMSUploadLifecycleService.exact_duplicate_job("b" * 64) is None
    finally:
        db.session.remove()
        db.drop_all()
        ctx.pop()


def test_hide_and_show_do_not_change_upload_status():
    app, ctx = _context()
    try:
        upload = IMSUpload(file_name="8.Hafta.xlsx", year=2033, month=2, week_number=8, status="COMPLETED")
        db.session.add(upload)
        db.session.commit()
        IMSUploadLifecycleService.set_hidden(upload.id, True)
        assert upload.id in IMSUploadLifecycleService.hidden_upload_ids()
        assert db.session.get(IMSUpload, upload.id).status == "COMPLETED"
        IMSUploadLifecycleService.set_hidden(upload.id, False)
        assert upload.id not in IMSUploadLifecycleService.hidden_upload_ids()
        assert Setting.query.filter_by(setting_key=IMSUploadLifecycleService.hidden_setting_key(upload.id)).first() is None
    finally:
        db.session.remove()
        db.drop_all()
        ctx.pop()


def test_latest_old_upload_without_snapshot_cannot_be_deleted():
    app, ctx = _context()
    try:
        upload = IMSUpload(
            file_name="legacy-8.Hafta.xlsx", year=2033, month=2, week_number=8,
            status="COMPLETED", reconciliation_status="PASSED",
        )
        db.session.add(upload)
        db.session.commit()
        allowed, reason = IMSUploadLifecycleService.can_delete(upload)
        assert allowed is False
        assert "snapshot" in reason.lower()
    finally:
        db.session.remove()
        db.drop_all()
        ctx.pop()


def test_delete_latest_restores_previous_period_state_and_removes_owned_rows():
    app, ctx = _context()
    try:
        rep, product, previous, target, summary = _seed_period()
        job = IMSImportJob(
            status=IMSImportJob.STATUS_PROCESSING,
            file_name="8.Hafta.xlsx",
            stored_file_name="8-staged.xlsx",
            source_hash="8" * 64,
            year=2033,
            month=2,
            clear_before_import=True,
            uploaded_by="Manager",
        )
        db.session.add(job)
        db.session.flush()
        IMSUploadLifecycleService.capture_period_snapshot(job_id=job.id, year=2033, month=2)

        current = IMSUpload(
            file_name="8.Hafta.xlsx", year=2033, month=2, quarter="Q1", week_number=8,
            status="COMPLETED", reconciliation_status="PASSED",
        )
        db.session.add(current)
        db.session.flush()
        current_id = int(current.id)
        previous_id = int(previous.id)
        target.unit_realization = 850.0
        target.tl_realization = 8500.0
        summary.upload_id = current_id
        summary.unit = 850.0
        summary.tl = 8500.0
        raw = IMSRawData(
            upload_id=current_id,
            year=2033,
            month=2,
            quarter="Q1",
            week_number=8,
            sheet_name="TTS HAFTALIK ÇIKIŞLARI",
            sheet_type="weekly",
            representative_id=rep.id,
            product_id=product.id,
            representative=rep.rep_name,
            product=product.product_name,
            unit=850.0,
            tl=8500.0,
            raw_json="{}",
        )
        db.session.add(raw)
        db.session.flush()
        fact = IMSFact(
            upload_id=current_id,
            raw_data_id=raw.id,
            representative_id=rep.id,
            product_id=product.id,
            year=2033,
            month=2,
            quarter="Q1",
            week_number=8,
            report_type="weekly_sales",
            unit=850.0,
            tl=8500.0,
            metrics_json="{}",
        )
        db.session.add(fact)
        job.status = IMSImportJob.STATUS_COMPLETED
        job.ims_upload_id = current_id
        db.session.commit()
        IMSUploadLifecycleService.finalize_snapshot(job_id=job.id, upload_id=current_id)

        result = IMSUploadLifecycleService.delete_upload(current_id)
        assert result["restored_previous_period_state"] is True
        assert db.session.get(IMSUpload, current_id) is None
        assert db.session.get(IMSUpload, previous_id) is not None
        restored_target = Target.query.filter_by(year=2033, month=2, representative_id=rep.id, product_id=product.id).one()
        restored_summary = IMSSummary.query.filter_by(year=2033, month=2, representative_id=rep.id, product_id=product.id).one()
        assert restored_target.unit_realization == 700.0
        assert restored_target.tl_realization == 7000.0
        assert restored_summary.unit == 700.0
        assert restored_summary.tl == 7000.0
        assert restored_summary.upload_id == previous_id
        assert IMSRawData.query.filter_by(upload_id=current_id).count() == 0
        assert IMSFact.query.filter_by(upload_id=current_id).count() == 0
        assert IMSImportJob.query.filter_by(ims_upload_id=current_id).count() == 0
    finally:
        db.session.remove()
        db.drop_all()
        ctx.pop()


def test_historical_upload_can_be_deleted_without_touching_current_period_state():
    app, ctx = _context()
    try:
        rep, product, previous, target, summary = _seed_period()
        current = IMSUpload(
            file_name="8.Hafta.xlsx", year=2033, month=2, quarter="Q1", week_number=8,
            status="COMPLETED", reconciliation_status="PASSED",
        )
        db.session.add(current)
        db.session.flush()
        summary.upload_id = current.id
        target.unit_realization = 850.0
        summary.unit = 850.0
        db.session.commit()

        allowed, _ = IMSUploadLifecycleService.can_delete(previous)
        assert allowed is True
        result = IMSUploadLifecycleService.delete_upload(previous.id)
        assert result["restored_previous_period_state"] is False
        assert Target.query.filter_by(year=2033, month=2).one().unit_realization == 850.0
        assert IMSSummary.query.filter_by(year=2033, month=2).one().unit == 850.0
        assert db.session.get(IMSUpload, current.id) is not None
    finally:
        db.session.remove()
        db.drop_all()
        ctx.pop()
