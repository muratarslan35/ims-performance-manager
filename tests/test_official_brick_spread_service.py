import os
import sys
import tempfile
from pathlib import Path

import pytest
from openpyxl import Workbook

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
MIGRATIONS_DIR = str(Path(__file__).resolve().parents[1] / "migrations")


@pytest.fixture()
def spread_app():
    os.environ.setdefault("APP_ENV", "development")
    os.environ.setdefault("SECRET_KEY", "test-secret-key")

    from app import create_app

    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)

    class TestConfig:
        TESTING = True
        SECRET_KEY = "test-secret-key"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{root / 'spread.db'}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        LOGIN_DISABLED = False
        TEST_USER_VAULT_ENABLED = True
        USER_VAULT_PATH = root / "users.db"
        UPLOAD_FOLDER = root / "uploads"
        REPORT_FOLDER = root / "reports"
        BACKUP_FOLDER = root / "backups"
        LOG_FOLDER = root / "logs"
        TEMP_FOLDER = root / "temp"

    application = create_app(TestConfig)
    with application.app_context():
        from flask_migrate import upgrade
        from app.database import initialize_database
        from app.extensions import db

        upgrade(directory=MIGRATIONS_DIR)
        initialize_database()
        db.session.remove()

    application.config["TEST_ROOT"] = root
    yield application

    with application.app_context():
        from app.extensions import db
        db.session.remove()
        db.engine.dispose()
    temp_dir.cleanup()


def _seed_master_data():
    from app.extensions import db
    from app.models import IMSUpload, Product, Representative
    from app.services.alias_service import AliasService

    representative = Representative(
        rep_code="REP001",
        rep_name="TEST TEMSILCI",
        region="901",
        city="DIYARBAKIR",
        active=True,
    )
    db.session.add(representative)

    # Product master is seeded by migrations in the real application.  Reuse
    # those rows instead of creating duplicate names in the fixture.
    product_names = ["Travazol", "Monurol", "Mixovul", "Fentivag", "Stiderm", "Acnemix", "Brimoder"]
    products = []
    for index, name in enumerate(product_names, start=1):
        product = Product.query.filter_by(product_name=name).first()
        if product is None:
            product = Product(product_code=f"P{index}", product_name=name, is_active=True)
            db.session.add(product)
        else:
            product.is_active = True
        products.append(product)

    # Keep this fixture scoped to the seven managed workbook products even if
    # a future migration introduces another product for another workflow.
    selected_ids = {product.id for product in products if product.id is not None}
    for product in Product.query.filter_by(is_active=True).all():
        if product.id not in selected_ids and product.product_name not in product_names:
            product.is_active = False

    upload = IMSUpload(
        file_name="4.Hafta.xlsx",
        year=2026,
        month=1,
        week_number=4,
        quarter="Q1",
        status="COMPLETED",
    )
    db.session.add(upload)
    db.session.commit()
    AliasService.clear_cache()
    return representative, products, upload


def _make_workbook(path: Path, products, representative_name="TEST TEMSILCI"):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Satış Brick Yayılımı"
    worksheet.append([None])
    worksheet.append(["BÖLGE", None, "Brick Sayısı", *[p.product_name for p in products], "TOPLAM"])
    worksheet.append([None, "NATIONAL", 0, 0, 0, 0, 0, 0, 0, 0, 0])
    worksheet.append(["901 DIYARBAKIR", "901 DIYARBAKIR", 1, 1, 1, 1, 1, 1, 1, 1, 1])
    worksheet.append(["901 DIYARBAKIR", representative_name, 6, 6, 5, 4, 1, 3, 6, 2, 6])
    workbook.save(path)
    workbook.close()


def test_official_spread_is_persisted_without_entering_sales_fact_domain(spread_app):
    from app.extensions import db
    from app.models import IMSRawData
    from app.services.official_brick_spread_service import OfficialBrickSpreadService

    with spread_app.app_context():
        representative, products, upload = _seed_master_data()
        workbook_path = spread_app.config["TEST_ROOT"] / "official-spread.xlsx"
        _make_workbook(workbook_path, products)

        result = OfficialBrickSpreadService.persist(
            file_path=workbook_path,
            upload_id=upload.id,
            year=2026,
            month=1,
            week_number=4,
        )
        db.session.commit()

        assert result["representatives"] == 1
        assert result["product_columns"] == 7
        assert result["records"] == 8

        rows = IMSRawData.query.filter_by(
            upload_id=upload.id,
            sheet_type=OfficialBrickSpreadService.SHEET_TYPE,
        ).all()
        assert len(rows) == 8
        assert all(row.product_id is None for row in rows)
        assert all(row.tl == 0 for row in rows)

        official = OfficialBrickSpreadService.for_representative(
            upload_id=upload.id,
            representative_id=representative.id,
        )
        assert official["total"] == 6
        assert official["products"]["Travazol"] == 6
        assert official["products"]["Monurol"] == 5
        assert official["products"]["Fentivag"] == 1
        assert official["source"] == "official_workbook_master"

        # Re-running is idempotent: no duplicate side-channel rows.
        OfficialBrickSpreadService.persist(
            file_path=workbook_path,
            upload_id=upload.id,
            year=2026,
            month=1,
            week_number=4,
        )
        db.session.commit()
        assert IMSRawData.query.filter_by(
            upload_id=upload.id,
            sheet_type=OfficialBrickSpreadService.SHEET_TYPE,
        ).count() == 8


def test_active_vacancy_does_not_capture_region_subtotal(spread_app):
    from app.extensions import db
    from app.models import Representative
    from app.services.alias_service import AliasService
    from app.services.official_brick_spread_service import OfficialBrickSpreadService

    with spread_app.app_context():
        _representative, products, upload = _seed_master_data()
        vacancy = Representative(
            rep_code="UNASSIGNED901DIYARBAKIRBOS",
            rep_name="ATANMAMIŞ · 901 DIYARBAKIR · DIYARBAKIR BOS",
            region="901",
            city="DIYARBAKIR",
            territory="DIYARBAKIR",
            team="TAYFUN-1",
            active=True,
        )
        db.session.add(vacancy)
        db.session.commit()
        AliasService.clear_cache()

        workbook_path = spread_app.config["TEST_ROOT"] / "active-vacancy-spread.xlsx"
        _make_workbook(workbook_path, products, representative_name="DIYARBAKIR BOS")

        result = OfficialBrickSpreadService.persist(
            file_path=workbook_path,
            upload_id=upload.id,
            year=2026,
            month=1,
            week_number=4,
        )
        db.session.commit()

        assert result["representatives"] == 1
        assert result["aggregate_rows_ignored"] == 2
        assert OfficialBrickSpreadService.for_representative(
            upload_id=upload.id,
            representative_id=vacancy.id,
        )["total"] == 6


def test_unmatched_master_representative_fails_instead_of_silently_dropping(spread_app):
    from app.extensions import db
    from app.services.official_brick_spread_service import (
        OfficialBrickSpreadError,
        OfficialBrickSpreadService,
    )

    with spread_app.app_context():
        _representative, products, upload = _seed_master_data()
        workbook_path = spread_app.config["TEST_ROOT"] / "unmatched-spread.xlsx"
        _make_workbook(workbook_path, products, representative_name="BILINMEYEN TEMSILCI")

        with pytest.raises(OfficialBrickSpreadError, match="eşleşmeyen temsilci"):
            OfficialBrickSpreadService.persist(
                file_path=workbook_path,
                upload_id=upload.id,
                year=2026,
                month=1,
                week_number=4,
            )
        db.session.rollback()


def test_official_spread_can_differ_from_derived_brick_count_by_design(spread_app):
    """Regression: official workbook count wins even if sale-bearing bricks are fewer."""
    from app.extensions import db
    from app.models import IMSRawData
    from app.services.official_brick_spread_service import OfficialBrickSpreadService

    with spread_app.app_context():
        representative, products, upload = _seed_master_data()
        workbook_path = spread_app.config["TEST_ROOT"] / "different-spread.xlsx"
        _make_workbook(workbook_path, products)

        # Only three sale-bearing bricks exist in raw sales, while the official
        # workbook states six distributed bricks for the representative.
        for source_row, brick in enumerate(("BRICK A", "BRICK B", "BRICK C"), start=10):
            db.session.add(IMSRawData(
                upload_id=upload.id,
                year=2026,
                month=1,
                week_number=4,
                quarter="Q1",
                sheet_name="1001 BRICK SATIS",
                sheet_type="brick_sales",
                source_row=source_row,
                representative_id=representative.id,
                product_id=products[0].id,
                representative=representative.rep_name,
                product=products[0].product_name,
                brick=brick,
                territory=brick,
                unit=1,
                tl=100,
                raw_json="{}",
            ))
        db.session.commit()

        OfficialBrickSpreadService.persist(
            file_path=workbook_path,
            upload_id=upload.id,
            year=2026,
            month=1,
            week_number=4,
        )
        db.session.commit()

        derived = db.session.query(IMSRawData.brick).filter_by(
            upload_id=upload.id,
            representative_id=representative.id,
            sheet_type="brick_sales",
        ).distinct().count()
        official = OfficialBrickSpreadService.for_representative(
            upload_id=upload.id,
            representative_id=representative.id,
        )
        assert derived == 3
        assert official["total"] == 6
