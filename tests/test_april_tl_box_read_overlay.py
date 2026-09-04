from decimal import Decimal
from pathlib import Path
import tempfile

from app import create_app
from app.extensions import db
from app.models import Product, Representative, Target
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


def test_week8_read_repair_cannot_restore_legacy_unit_after_april():
    app = create_app(Config)
    with app.app_context():
        db.create_all()
        product = Product(
            product_code="BRIMODER",
            product_name="Brimoder",
            unit_price=827.56,
            is_active=True,
        )
        representative = Representative(
            rep_code="DIY-REP",
            rep_name="Diyarbakır Temsilcisi",
            region="901",
            city="Diyarbakır",
            active=True,
        )
        db.session.add_all([product, representative])
        db.session.flush()
        target = Target(
            year=2026,
            month=4,
            representative_id=representative.id,
            product_id=product.id,
            tl_target=13512.0,
            unit_target=16.0,
            tl_realization=9931.0,
            # Legacy IMS unit is intentionally wrong. The read repair must not
            # put this value back after ProductionResultService derived 12 boxes.
            unit_realization=703.0,
        )
        db.session.add(target)
        db.session.flush()

        rows = {
            product.id: {
                "source": "IMS",
                "complete": True,
                "target_tl": Decimal("13512"),
                "target_unit": Decimal("16"),
                "actual_tl": Decimal("9931"),
                "actual_unit": Decimal("12"),
            }
        }
        repaired = _apply_target_ims_actuals(
            rows,
            [target],
            has_completed_ims=True,
            year=2026,
            month=4,
        )

        assert repaired[product.id]["actual_tl"] == Decimal("9931")
        assert repaired[product.id]["actual_unit"] == Decimal("12")
        assert repaired[product.id]["actual_unit"] != Decimal("703")

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
