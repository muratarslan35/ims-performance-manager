from datetime import datetime
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
from app.services.production_result_service import ProductionResultService


MIGRATIONS_DIR = str(Path(__file__).resolve().parents[1] / "migrations")


def _app(tmp_path):
    class Config:
        TESTING = True
        SECRET_KEY = "production-batch-test"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'production-batch.db'}"
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


def _seed(tmp_path):
    representative = Representative(rep_code="BATCH1", rep_name="BATCH TEMSILCI", active=True)
    products = [
        Product(product_code=f"B{index}", product_name=f"Batch Product {index}", is_active=True)
        for index in range(1, 8)
    ]
    db.session.add(representative)
    db.session.add_all(products)
    db.session.flush()
    representative_id = representative.id
    product_ids = [product.id for product in products]

    ims_upload = IMSUpload(
        file_name="batch-ims.xlsx", year=2026, month=8, quarter="Q3",
        status="COMPLETED", completed_at=datetime(2026, 8, 19, 8, 0),
    )
    db.session.add(ims_upload)
    db.session.flush()
    for index, product in enumerate(products, start=1):
        db.session.add(Target(
            year=2026, month=8, quarter="Q3", representative_id=representative_id,
            product_id=product.id, tl_target=100.0, unit_target=10.0,
        ))
        db.session.add(IMSSummary(
            upload_id=ims_upload.id, year=2026, month=8, quarter="Q3",
            representative_id=representative_id, product_id=product.id,
            tl=50.0 + index, unit=5.0 + index / 10,
            target_tl=100.0, target_unit=10.0,
        ))

    p1 = ProductionResultUpload(
        file_name="p1.xlsx", stored_file_name="p1.xlsx", source_hash="1" * 64,
        year=2026, month=8, production_stage=1,
        status=ProductionResultUpload.STATUS_APPLIED,
        applied_at=datetime(2026, 8, 20, 8, 0),
    )
    p2 = ProductionResultUpload(
        file_name="p2.xlsx", stored_file_name="p2.xlsx", source_hash="2" * 64,
        year=2026, month=8, production_stage=2,
        status=ProductionResultUpload.STATUS_APPLIED,
        applied_at=datetime(2026, 8, 21, 8, 0),
    )
    db.session.add_all([p1, p2])
    db.session.flush()
    # Product 1 is authoritative P2 and intentionally exceeds 100%.
    db.session.add(ProductionResult(
        upload_id=p2.id, representative_id=representative_id,
        product_id=products[0].id, realization_percent=125.5,
    ))
    # Product 2 is absent from P2, so it must fall back to P1.
    db.session.add(ProductionResult(
        upload_id=p1.id, representative_id=representative_id,
        product_id=products[1].id, realization_percent=110.0,
    ))
    db.session.commit()
    return representative_id, product_ids


def test_batch_resolution_preserves_product_level_p2_p1_ims_priority(tmp_path):
    application = _app(tmp_path)
    with application.app_context():
        representative_id, product_ids = _seed(tmp_path)
        rows = ProductionResultService.effective_products(2026, 8, representative_id, product_ids)

        assert rows[product_ids[0]]["source"] == "PRODUCTION_2"
        assert rows[product_ids[0]]["realization_percent"] == Decimal("125.5")
        assert rows[product_ids[0]]["actual_unit"] == Decimal("12.55")
        assert rows[product_ids[1]]["source"] == "PRODUCTION_1"
        assert rows[product_ids[1]]["realization_percent"] == Decimal("110.0")
        assert rows[product_ids[2]]["source"] == "IMS"
        assert rows[product_ids[2]]["complete"] is True


def test_batch_context_eliminates_per_product_query_fanout(tmp_path):
    application = _app(tmp_path)
    with application.app_context():
        representative_id, product_ids = _seed(tmp_path)
        selects = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        event.listen(db.engine, "before_cursor_execute", capture)
        try:
            rows = ProductionResultService.effective_products(2026, 8, representative_id, product_ids)
            prefetch_count = len(selects)
            with ProductionResultService.use_effective_batch(2026, 8, representative_id, rows):
                results = [
                    ProductionResultService.effective_product(2026, 8, representative_id, product_id)
                    for product_id in product_ids
                ]
            after_context_count = len(selects)
        finally:
            event.remove(db.engine, "before_cursor_execute", capture)

        assert prefetch_count <= 4
        assert after_context_count == prefetch_count
        assert [row["source"] for row in results[:3]] == ["PRODUCTION_2", "PRODUCTION_1", "IMS"]


def test_april_onward_ims_uses_tl_price_boxes_and_half_down_rounding(tmp_path):
    application = _app(tmp_path)
    with application.app_context():
        rep = Representative(rep_code="TLBOX", rep_name="TL KUTU", active=True)
        product = Product(
            product_code="TRV", product_name="Travazol", unit_price=128.31, is_active=True
        )
        db.session.add_all([rep, product]); db.session.flush()
        upload = IMSUpload(file_name="week16.xlsx", year=2026, month=4, status="COMPLETED")
        db.session.add(upload); db.session.flush()
        db.session.add(Target(
            year=2026, month=4, quarter="Q2", representative_id=rep.id, product_id=product.id,
            tl_target=1068003.3058255836, unit_target=999999,
        ))
        db.session.add(IMSSummary(
            upload_id=upload.id, year=2026, month=4,
            quarter="Q2",
            representative_id=rep.id, product_id=product.id,
            tl=416109.33, unit=-999999,
        ))
        db.session.commit()

        result = ProductionResultService.effective_product(2026, 4, rep.id, product.id)
        assert result["source"] == "IMS"
        assert result["target_unit"] == Decimal("8324")
        assert result["actual_unit"] == Decimal("3243")
