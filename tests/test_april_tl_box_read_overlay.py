from decimal import Decimal
from pathlib import Path
import tempfile

from app import create_app
from app.extensions import db
from app.models import IMSSummary, IMSUpload, Product, Representative, Target
from app.services.production_result_service import ProductionResultService
from app.services.region_performance_service import RegionPerformanceService
from app.services.tl_box_calculation_service import TLBoxCalculationService
from app.services.week8_read_path_repair import _apply_target_ims_actuals


class Config:
    TESTING = True
    SECRET_KEY = "april-tl-box-overlay"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = Path(tempfile.gettempdir()) / "april-tl-box-overlay-uploads"
    REPORT_FOLDER = Path(tempfile.gettempdir()) / "april-tl-box-overlay-reports"
    BACKUP_FOLDER = Path(tempfile.gettempdir()) / "april-tl-box-overlay-backups"
    LOG_FOLDER = Path(tempfile.gettempdir()) / "april-tl-box-overlay-logs"


PRODUCTS = (
    # name, price, target TL, actual TL, expected target box, expected actual box,
    # deliberately-wrong legacy IMS unit realization
    ("TRAVAZOL", 128.31, 1068003, 416109, 8324, 3243, -50000),
    ("MONUROL", 100.37, 360500, 115927, 3592, 1155, 99155),
    ("ACNEMIX", 230.57, 211004, 224806, 915, 975, -7000),
    ("MIXOVUL", 160.89, 72425, 39096, 450, 243, 3243),
    ("STIDERM", 100.37, 54745, 58516, 545, 583, -8798),
    ("BRIMODER", 827.56, 13512, 9931, 16, 12, 703),
    ("FENTIVAG", 179.10, 0, 0, 0, 0, -133),
)


def _seed_seven_products():
    representative = Representative(
        rep_code="DIY-REP",
        rep_name="Diyarbakır Temsilcisi",
        region="901",
        city="Diyarbakır",
        active=True,
    )
    db.session.add(representative)
    db.session.flush()

    upload = IMSUpload(
        file_name="16.Hafta.xlsx",
        year=2026,
        month=4,
        week_number=16,
        status="COMPLETED",
    )
    db.session.add(upload)
    db.session.flush()

    targets = []
    products = []
    for index, (name, price, target_tl, actual_tl, _target_box, _actual_box, legacy_unit) in enumerate(PRODUCTS, start=1):
        product = Product(
            product_code=name,
            product_name=name.title(),
            unit_price=price,
            display_order=index,
            is_active=True,
        )
        db.session.add(product)
        db.session.flush()
        target = Target(
            year=2026,
            month=4,
            quarter="Q2",
            representative_id=representative.id,
            product_id=product.id,
            tl_target=target_tl,
            # Deliberately wrong legacy unit values prove that April+ reads do
            # not trust historical IMS box fields.
            unit_target=999999 if target_tl else 0,
            tl_realization=actual_tl,
            unit_realization=legacy_unit,
        )
        summary = IMSSummary(
            upload_id=upload.id,
            year=2026,
            month=4,
            quarter="Q2",
            representative_id=representative.id,
            product_id=product.id,
            target_tl=target_tl,
            target_unit=999999 if target_tl else 0,
            tl=actual_tl,
            unit=legacy_unit,
        )
        db.session.add_all([target, summary])
        targets.append(target)
        products.append(product)
    db.session.commit()
    return representative, products, targets


def test_april_read_path_uses_tl_price_for_all_seven_products():
    app = create_app(Config)
    with app.app_context():
        db.create_all()
        representative, products, targets = _seed_seven_products()

        resolved = ProductionResultService.effective_products(2026, 4, representative.id)
        by_name = {product.product_code: resolved[product.id] for product in products}

        for name, price, target_tl, actual_tl, target_box, actual_box, legacy_unit in PRODUCTS:
            row = by_name[name]
            assert row["source"] == "IMS"
            assert row["target_tl"] == Decimal(str(target_tl))
            assert row["actual_tl"] == Decimal(str(actual_tl))
            assert row["target_unit"] == Decimal(str(target_box))
            assert row["actual_unit"] == Decimal(str(actual_box))
            assert row["actual_unit"] != Decimal(str(legacy_unit))
            assert row["target_unit"] - row["actual_unit"] == Decimal(str(target_box - actual_box))
            assert row["target_unit"] == TLBoxCalculationService.boxes_from_tl(target_tl, price)
            assert row["actual_unit"] == TLBoxCalculationService.boxes_from_tl(actual_tl, price)

        # The Week-8 compatibility overlay must preserve the same April rule for
        # every product instead of restoring Target.unit_realization.
        repaired = _apply_target_ims_actuals(
            {product.id: dict(resolved[product.id]) for product in products},
            targets,
            has_completed_ims=True,
            year=2026,
            month=4,
        )
        for product, spec in zip(products, PRODUCTS):
            name, _price, target_tl, actual_tl, target_box, actual_box, legacy_unit = spec
            row = repaired[product.id]
            assert row["target_tl"] == Decimal(str(target_tl)), name
            assert row["actual_tl"] == Decimal(str(actual_tl)), name
            assert row["target_unit"] == Decimal(str(target_box)), name
            assert row["actual_unit"] == Decimal(str(actual_box)), name
            assert row["actual_unit"] != Decimal(str(legacy_unit)), name

        db.session.remove()
        db.drop_all()


def test_april_region_aggregation_uses_same_seven_product_box_authority():
    app = create_app(Config)
    with app.app_context():
        db.create_all()
        _representative, products, _targets = _seed_seven_products()

        monthly = RegionPerformanceService("901", 2026, 4).report()["periods"]["monthly"]
        rows = {item["product_name"].upper(): item for item in monthly["products"]}

        for product, spec in zip(products, PRODUCTS):
            name, _price, target_tl, actual_tl, target_box, actual_box, _legacy_unit = spec
            row = rows[product.product_name.upper()]
            assert row["target_tl"] == Decimal(str(target_tl)), name
            assert row["actual_tl"] == Decimal(str(actual_tl)), name
            assert row["target_unit"] == Decimal(str(target_box)), name
            assert row["actual_unit"] == Decimal(str(actual_box)), name
            assert row["unit_difference"] == Decimal(str(actual_box - target_box)), name

        db.session.remove()
        db.drop_all()


def test_pre_april_read_repair_keeps_legacy_unit_authority():
    rows = {
        7: {
            "source": "IMS",
            "complete": True,
            "target_tl": Decimal("1000"),
            "actual_tl": Decimal("900"),
            "actual_unit": Decimal("8"),
        }
    }

    class LegacyTarget:
        product_id = 7
        tl_target = 1000
        tl_realization = 900
        unit_realization = 11

    repaired = _apply_target_ims_actuals(
        rows,
        [LegacyTarget()],
        has_completed_ims=True,
        year=2026,
        month=3,
    )
    assert repaired[7]["actual_unit"] == Decimal("11")
