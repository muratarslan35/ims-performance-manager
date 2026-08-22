from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from flask_migrate import upgrade
from sqlalchemy import event

from app import create_app
from app.extensions import db
from app.models import (
    IMSSummary,
    IMSUpload,
    Product,
    ProductionResult,
    ProductionResultUpload,
    Representative,
    Target,
)
from app.services.representative_period_snapshot_service import RepresentativePeriodSnapshotService
from app.services.scoped_ai_insight_service import ScopedAIInsightService


MIGRATIONS_DIR = str(Path(__file__).resolve().parents[1] / "migrations")


def _app(tmp_path):
    class Config:
        TESTING = True
        SECRET_KEY = "representative-period-performance-test"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'representative-period-performance.db'}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = tmp_path / "uploads"
        REPORT_FOLDER = tmp_path / "reports"
        BACKUP_FOLDER = tmp_path / "backups"
        LOG_FOLDER = tmp_path / "logs"
        TEMP_FOLDER = tmp_path / "temp"

    application = create_app(Config)
    with application.app_context():
        upgrade(directory=MIGRATIONS_DIR)
    return application


def _production_upload(year, month, stage, applied_at, suffix):
    return ProductionResultUpload(
        file_name=f"production-{suffix}.xlsx",
        stored_file_name=f"production-{suffix}.xlsx",
        source_hash=(suffix * 64)[:64],
        year=year,
        month=month,
        production_stage=stage,
        status=ProductionResultUpload.STATUS_APPLIED,
        applied_at=applied_at,
    )


def _ims_upload(year, month):
    upload = IMSUpload(
        file_name=f"ims-{year}-{month:02d}.xlsx",
        year=year,
        month=month,
        status="COMPLETED",
        completed_at=datetime(year, month, 20, 8, 0),
    )
    db.session.add(upload)
    db.session.flush()
    return upload


def _quarter(month):
    return f"Q{((int(month) - 1) // 3) + 1}"


def test_period_snapshot_preserves_p2_p1_ims_priority_and_over_100(tmp_path):
    application = _app(tmp_path)
    with application.app_context():
        representative = Representative(rep_code="PERIOD1", rep_name="PERIOD TEMSILCI", active=True)
        product_a = Product(product_code="PA", product_name="Product A", is_active=True)
        product_b = Product(product_code="PB", product_name="Product B", is_active=True)
        db.session.add_all([representative, product_a, product_b])
        db.session.flush()
        representative_id = representative.id

        # Six months of authoritative targets and IMS fallback summaries.
        for month in range(3, 9):
            ims_upload = _ims_upload(2026, month)
            for product, ims_tl in ((product_a, 70.0 + month), (product_b, 60.0 + month)):
                db.session.add(Target(
                    year=2026,
                    month=month,
                    quarter=_quarter(month),
                    representative_id=representative_id,
                    product_id=product.id,
                    tl_target=100.0,
                    unit_target=10.0,
                ))
                db.session.add(IMSSummary(
                    upload_id=ims_upload.id,
                    year=2026,
                    month=month,
                    quarter=_quarter(month),
                    representative_id=representative_id,
                    product_id=product.id,
                    tl=ims_tl,
                    unit=ims_tl / 10,
                    target_tl=100.0,
                    target_unit=10.0,
                ))

        # August has both stages. Product A exists in P2 (>100% and uncapped).
        # Product B is missing from P2, therefore canonical logic must fall back
        # to P1 rather than treating P2 as an all-product replacement.
        p1 = _production_upload(2026, 8, 1, datetime(2026, 8, 20, 9, 0), "a")
        p2 = _production_upload(2026, 8, 2, datetime(2026, 8, 21, 9, 0), "b")
        db.session.add_all([p1, p2])
        db.session.flush()
        db.session.add_all([
            ProductionResult(
                upload_id=p2.id,
                representative_id=representative_id,
                product_id=product_a.id,
                realization_percent=125.5,
            ),
            ProductionResult(
                upload_id=p1.id,
                representative_id=representative_id,
                product_id=product_a.id,
                realization_percent=90.0,
            ),
            ProductionResult(
                upload_id=p1.id,
                representative_id=representative_id,
                product_id=product_b.id,
                realization_percent=110.0,
            ),
        ])
        db.session.commit()

        periods = ScopedAIInsightService.representative_periods(representative_id, 2026, 8)
        monthly = periods["monthly"]
        product_rows = {row["product_name"]: row for row in monthly["products"]}

        assert monthly["complete"] is True
        assert monthly["target_tl"] == Decimal("200.0")
        assert monthly["actual_tl"] == Decimal("235.500")
        assert monthly["realization_percent"] == 117.8
        assert product_rows["Product A"]["actual_tl"] == Decimal("125.500")
        assert product_rows["Product A"]["realization_percent"] == 125.5
        assert product_rows["Product B"]["actual_tl"] == Decimal("110.0")
        assert product_rows["Product B"]["realization_percent"] == 110.0

        # Earlier months have no production result and therefore stay on IMS.
        half_year = periods["half_year"]
        expected_ims = sum((70.0 + month) + (60.0 + month) for month in range(3, 8))
        assert float(half_year["actual_tl"]) == expected_ims + 235.5


def test_period_snapshot_uses_bounded_query_count_for_six_months(tmp_path):
    application = _app(tmp_path)
    with application.app_context():
        representative = Representative(rep_code="PERIOD2", rep_name="PERIOD TEMSILCI 2", active=True)
        products = [
            Product(product_code=f"P{index}", product_name=f"Product {index}", is_active=True)
            for index in range(7)
        ]
        db.session.add(representative)
        db.session.add_all(products)
        db.session.flush()
        representative_id = representative.id

        for month in range(3, 9):
            ims_upload = _ims_upload(2026, month)
            for product in products:
                db.session.add(Target(
                    year=2026,
                    month=month,
                    quarter=_quarter(month),
                    representative_id=representative_id,
                    product_id=product.id,
                    tl_target=100.0,
                    unit_target=10.0,
                ))
                db.session.add(IMSSummary(
                    upload_id=ims_upload.id,
                    year=2026,
                    month=month,
                    quarter=_quarter(month),
                    representative_id=representative_id,
                    product_id=product.id,
                    tl=80.0,
                    unit=8.0,
                    target_tl=100.0,
                    target_unit=10.0,
                ))
        db.session.commit()

        selects = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(" ".join(statement.split()))

        event.listen(db.engine, "before_cursor_execute", capture)
        try:
            periods = RepresentativePeriodSnapshotService.build(representative_id, 2026, 8)
        finally:
            event.remove(db.engine, "before_cursor_execute", capture)

        assert periods["monthly"]["actual_tl"] == Decimal("560.0")
        assert periods["half_year"]["actual_tl"] == Decimal("3360.0")
        # Targets, summaries, production uploads and products. Production-result
        # rows are skipped entirely because there are no applied uploads.
        assert len(selects) <= 4
        assert sum(" TARGETS " in statement.upper() for statement in selects) == 1
        assert sum(" IMS_SUMMARY " in statement.upper() for statement in selects) == 1
        assert sum(" PRODUCTION_RESULT_UPLOADS " in statement.upper() for statement in selects) == 1


def test_period_snapshot_query_count_stays_constant_with_production_rows(tmp_path):
    application = _app(tmp_path)
    with application.app_context():
        representative = Representative(rep_code="PERIOD3", rep_name="PERIOD TEMSILCI 3", active=True)
        product = Product(product_code="PC", product_name="Product C", is_active=True)
        db.session.add_all([representative, product])
        db.session.flush()
        representative_id = representative.id
        for month in range(3, 9):
            ims_upload = _ims_upload(2026, month)
            db.session.add(Target(
                year=2026,
                month=month,
                quarter=_quarter(month),
                representative_id=representative_id,
                product_id=product.id,
                tl_target=100.0,
                unit_target=10.0,
            ))
            db.session.add(IMSSummary(
                upload_id=ims_upload.id,
                year=2026,
                month=month,
                quarter=_quarter(month),
                representative_id=representative_id,
                product_id=product.id,
                tl=75.0,
                unit=7.5,
                target_tl=100.0,
                target_unit=10.0,
            ))
            upload = _production_upload(
                2026, month, 1,
                datetime(2026, month, 20, 9, 0) + timedelta(minutes=month),
                chr(96 + month),
            )
            db.session.add(upload)
            db.session.flush()
            db.session.add(ProductionResult(
                upload_id=upload.id,
                representative_id=representative_id,
                product_id=product.id,
                realization_percent=100.0 + month,
            ))
        db.session.commit()

        selects = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        event.listen(db.engine, "before_cursor_execute", capture)
        try:
            periods = RepresentativePeriodSnapshotService.build(representative_id, 2026, 8)
        finally:
            event.remove(db.engine, "before_cursor_execute", capture)

        assert periods["monthly"]["realization_percent"] == 108.0
        assert periods["half_year"]["complete"] is True
        # One extra SELECT fetches all ProductionResult rows for all selected
        # uploads; count does not scale with 42/70 target evaluations.
        assert len(selects) <= 5
        assert sum("PRODUCTION_RESULTS" in statement.upper() for statement in selects) == 1
