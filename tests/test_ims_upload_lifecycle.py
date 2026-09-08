from pathlib import Path
import hashlib
import json
import tempfile
import pytest

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
from app.services.persistent_region_snapshot_service import (
    region_snapshot_sets,
    region_snapshots,
)
from app.services.persistent_representative_snapshot_service import (
    representative_snapshot_sets,
    representative_snapshots,
)
from app.services.persistent_dashboard_snapshot_service import PersistentDashboardSnapshotService


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
        assert "önceki temiz ims" in reason.lower()
    finally:
        db.session.remove()
        db.drop_all()
        ctx.pop()


def test_delete_latest_fails_closed_without_complete_rollback_assets():
    app, ctx = _context()
    try:
        rep, product, previous, target, summary = _seed_period()
        rep_id = int(rep.id)
        product_id = int(product.id)
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
        snapshot_path = IMSUploadLifecycleService.capture_period_snapshot(job_id=job.id, year=2033, month=2)
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        assert snapshot["targets"][0]["unit_realization"] == 700.0
        assert snapshot["summaries"][0]["unit"] == 700.0

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
            representative_id=rep_id,
            product_id=product_id,
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
            representative_id=rep_id,
            product_id=product_id,
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
        final_snapshot_path = IMSUploadLifecycleService.finalize_snapshot(job_id=job.id, upload_id=current_id)
        final_snapshot = json.loads(final_snapshot_path.read_text(encoding="utf-8"))
        assert final_snapshot["targets"][0]["unit_realization"] == 700.0
        assert final_snapshot["summaries"][0]["unit"] == 700.0

        with pytest.raises(RuntimeError, match="arşiv kaynak"):
            IMSUploadLifecycleService.delete_upload(current_id)
        assert db.session.get(IMSUpload, current_id) is not None
        assert db.session.get(IMSUpload, previous_id) is not None

        raw_target = db.session.execute(
            Target.__table__.select().where(
                Target.__table__.c.year == 2033,
                Target.__table__.c.month == 2,
                Target.__table__.c.representative_id == rep_id,
                Target.__table__.c.product_id == product_id,
            )
        ).mappings().one()
        raw_summary = db.session.execute(
            IMSSummary.__table__.select().where(
                IMSSummary.__table__.c.year == 2033,
                IMSSummary.__table__.c.month == 2,
                IMSSummary.__table__.c.representative_id == rep_id,
                IMSSummary.__table__.c.product_id == product_id,
            )
        ).mappings().one()
        assert raw_target["unit_realization"] == 850.0
        assert raw_target["tl_realization"] == 8500.0
        assert raw_summary["unit"] == 850.0
        assert raw_summary["tl"] == 8500.0
        assert raw_summary["upload_id"] == current_id
        assert IMSRawData.query.filter_by(upload_id=current_id).count() == 1
        assert IMSFact.query.filter_by(upload_id=current_id).count() == 1
        assert IMSImportJob.query.filter_by(ims_upload_id=current_id).count() == 1
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


def test_archived_source_hash_mismatch_fails_closed():
    app, ctx = _context()
    upload_id = 0
    try:
        upload = IMSUpload(
            file_name="7.Hafta.xlsx", year=2033, month=2, week_number=7,
            status=IMSUpload.STATUS_COMPLETED,
        )
        db.session.add(upload)
        db.session.flush()
        upload_id = int(upload.id)
        db.session.add(IMSImportJob(
            status=IMSImportJob.STATUS_COMPLETED,
            file_name=upload.file_name,
            stored_file_name="stored.xlsx",
            source_hash=hashlib.sha256(b"expected").hexdigest(),
            year=2033,
            month=2,
            clear_before_import=False,
            uploaded_by="Manager",
            ims_upload_id=upload_id,
        ))
        db.session.commit()
        IMSUploadLifecycleService.archived_source_path(upload_id).write_bytes(b"tampered")

        with pytest.raises(RuntimeError, match="SHA-256"):
            IMSUploadLifecycleService._validate_archived_source(upload_id)
    finally:
        if upload_id:
            IMSUploadLifecycleService.archived_source_path(upload_id).unlink(missing_ok=True)
        db.session.remove()
        db.drop_all()
        ctx.pop()


def test_master_changed_after_import_refuses_automatic_rollback():
    app, ctx = _context()
    current_id = 0
    try:
        rep, _product, previous, _target, _summary = _seed_period()
        job = IMSImportJob(
            status=IMSImportJob.STATUS_PROCESSING,
            file_name="8.Hafta.xlsx",
            stored_file_name="stored.xlsx",
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
            file_name="8.Hafta.xlsx", year=2033, month=2, week_number=8,
            status=IMSUpload.STATUS_COMPLETED,
        )
        db.session.add(current)
        db.session.flush()
        current_id = int(current.id)
        rep.active = False
        job.status = IMSImportJob.STATUS_COMPLETED
        job.ims_upload_id = current_id
        db.session.commit()
        IMSUploadLifecycleService.finalize_snapshot(job_id=job.id, upload_id=current_id)
        IMSUploadLifecycleService.seal_snapshot_master_state(upload_id=current_id)

        rep.active = True
        db.session.commit()
        with pytest.raises(RuntimeError, match="ayrıca değiştirildi"):
            IMSUploadLifecycleService._validated_snapshot_payload(current, previous.id)
    finally:
        if current_id:
            IMSUploadLifecycleService.upload_snapshot_path(current_id).unlink(missing_ok=True)
        db.session.remove()
        db.drop_all()
        ctx.pop()


def test_instant_rollback_switches_to_previous_generation_without_deleting_bad_upload():
    app, ctx = _context()
    previous_id = current_id = 0
    try:
        rep, product, previous, target, summary = _seed_period()
        previous_id = int(previous.id)
        previous_bytes = b"previous-workbook"
        db.session.add(IMSImportJob(
            status=IMSImportJob.STATUS_COMPLETED,
            file_name=previous.file_name,
            stored_file_name="previous-staged.xlsx",
            source_hash=hashlib.sha256(previous_bytes).hexdigest(),
            year=2033,
            month=2,
            clear_before_import=False,
            uploaded_by="Manager",
            ims_upload_id=previous_id,
        ))
        db.session.commit()
        PersistentDashboardSnapshotService.publish(2033, 2, {"upload_id": previous_id})
        job = IMSImportJob(
            status=IMSImportJob.STATUS_PROCESSING,
            file_name="8.Hafta.xlsx",
            stored_file_name="instant-rollback.xlsx",
            source_hash="9" * 64,
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
            status=IMSUpload.STATUS_COMPLETED, reconciliation_status="PASSED",
        )
        db.session.add(current)
        db.session.flush()
        current_id = int(current.id)
        target.unit_realization = 850.0
        summary.upload_id = current_id
        summary.unit = 850.0
        rep.active = False
        wrong_rep = Representative(
            rep_code="WRONG-REP", rep_name="Wrong Imported Rep", active=True,
        )
        wrong_product = Product(
            product_code="WRONG-PROD", product_name="Wrong Imported Product", is_active=True,
        )
        db.session.add_all([wrong_rep, wrong_product])
        db.session.flush()
        wrong_rep_id, wrong_product_id = int(wrong_rep.id), int(wrong_product.id)
        job.status = IMSImportJob.STATUS_COMPLETED
        job.ims_upload_id = current_id
        db.session.commit()
        IMSUploadLifecycleService.finalize_snapshot(job_id=job.id, upload_id=current_id)
        IMSUploadLifecycleService.seal_snapshot_master_state(upload_id=current_id)
        IMSUploadLifecycleService.archived_source_path(previous_id).write_bytes(previous_bytes)

        region_result = db.session.execute(region_snapshot_sets.insert().values(
            year=2033, month=2, source_upload_id=previous_id, production_upload_id=0,
            status="SUPERSEDED", region_count=1,
        ))
        region_set_id = int(region_result.inserted_primary_key[0])
        db.session.execute(region_snapshots.insert().values(
            set_id=region_set_id, region_key="901", payload_json="{}",
        ))
        rep_result = db.session.execute(representative_snapshot_sets.insert().values(
            year=2033, month=2, source_upload_id=previous_id, production_upload_id=0,
            status="SUPERSEDED", representative_count=1,
        ))
        rep_set_id = int(rep_result.inserted_primary_key[0])
        db.session.execute(representative_snapshots.insert().values(
            set_id=rep_set_id, representative_id=rep.id, payload_json="{}",
        ))
        db.session.commit()

        result = IMSUploadLifecycleService.rollback_to_previous(current_id)

        assert result["active_upload_id"] == previous_id
        assert db.session.get(IMSUpload, current_id).status == IMSUpload.STATUS_ROLLED_BACK
        assert db.session.get(IMSUpload, previous_id).status == IMSUpload.STATUS_COMPLETED
        assert IMSSummary.query.filter_by(year=2033, month=2).one().upload_id == previous_id
        assert IMSSummary.query.filter_by(year=2033, month=2).one().unit == 700.0
        assert Target.query.filter_by(year=2033, month=2).one().unit_realization == 700.0
        assert db.session.get(Representative, rep.id).active is True
        assert db.session.get(Representative, wrong_rep_id).active is False
        assert db.session.get(Product, wrong_product_id).is_active is False
        assert IMSImportJob.query.filter_by(ims_upload_id=current_id).count() == 1
        assert db.session.execute(
            region_snapshot_sets.select().where(region_snapshot_sets.c.id == region_set_id)
        ).mappings().one()["status"] == "ACTIVE"
        assert db.session.execute(
            representative_snapshot_sets.select().where(representative_snapshot_sets.c.id == rep_set_id)
        ).mappings().one()["status"] == "ACTIVE"

        cleanup = IMSUploadLifecycleService.delete_upload(current_id)
        assert cleanup["master_cleanup"]["representatives_deleted"] == 1
        assert cleanup["master_cleanup"]["products_deleted"] == 1
        assert db.session.get(Representative, wrong_rep_id) is None
        assert db.session.get(Product, wrong_product_id) is None
    finally:
        if previous_id:
            IMSUploadLifecycleService.archived_source_path(previous_id).unlink(missing_ok=True)
        if current_id:
            IMSUploadLifecycleService.upload_snapshot_path(current_id).unlink(missing_ok=True)
        db.session.remove()
        db.drop_all()
        ctx.pop()
