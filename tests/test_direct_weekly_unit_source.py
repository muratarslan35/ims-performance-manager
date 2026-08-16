from pathlib import Path
import tempfile

import pandas as pd

from app import create_app
from app.extensions import db
from app.models import IMSSummary, Product, Representative, Target
from app.services.alias_service import AliasService
from app.services.ims_import_service import IMSImportService


class DirectUnitTestConfig:
    TESTING = True
    SECRET_KEY = "direct-unit-test"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = Path(tempfile.gettempdir()) / "direct-unit-uploads"
    REPORT_FOLDER = Path(tempfile.gettempdir()) / "direct-unit-reports"
    BACKUP_FOLDER = Path(tempfile.gettempdir()) / "direct-unit-backups"
    LOG_FOLDER = Path(tempfile.gettempdir()) / "direct-unit-logs"


def test_weekly_summary_uses_explicit_cumulative_box_value_not_tl_derivation():
    app = create_app(DirectUnitTestConfig)
    with app.app_context():
        db.create_all()
        travazol = Product(product_code="TRAVAZOL", product_name="Travazol", is_active=True)
        monurol = Product(product_code="MONUROL", product_name="Monurol", is_active=True)
        representative = Representative(rep_code="DIRECT-REP", rep_name="DIRECT UNIT REP", active=True)
        db.session.add_all([travazol, monurol, representative])
        db.session.flush()
        target = Target(
            year=2032,
            month=1,
            quarter="Q1",
            representative_id=representative.id,
            product_id=travazol.id,
            tl_target=1000.0,
            unit_target=10.0,
        )
        summary = IMSSummary(
            year=2032,
            month=1,
            quarter="Q1",
            representative_id=representative.id,
            product_id=travazol.id,
            tl=0.0,
            unit=0.0,
        )
        db.session.add_all([target, summary])
        db.session.flush()

        service = IMSImportService("unused.xlsx")
        service.workbook = {
            "TTS HAFTALIK ÇIKIŞLARI": pd.DataFrame(
                [
                    [None, None, "1-18 OCAK TL ÇIKIŞI", None, "1-18 OCAK KUTU ÇIKIŞI", None],
                    [None, None, "TRAVAZOL", "MONUROL", "TRAVAZOL", "MONUROL"],
                    ["901 DIYARBAKIR", "DIRECT UNIT REP", 500.0, 0.0, 37.0, 0.0],
                ]
            )
        }

        def product_match(name):
            normalized = AliasService.normalize(name)
            product = travazol if normalized == "TRAVAZOL" else monurol if normalized == "MONUROL" else None
            return {"matched": product is not None, "object": product}

        service.resolve_product_match = product_match
        service.resolve_representative_match = lambda name: {
            "matched": AliasService.normalize(name) == "DIRECT UNIT REP",
            "object": representative,
        }

        result = service.apply_weekly_sales_summary(2032, 1)
        db.session.flush()

        assert result["updated_values"] == 1
        assert summary.tl == 500.0
        assert summary.unit == 37.0
        assert target.tl_realization == 500.0
        assert target.unit_realization == 37.0
        assert target.unit_realization != 5.0
