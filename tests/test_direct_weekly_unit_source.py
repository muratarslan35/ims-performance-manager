from pathlib import Path
import tempfile

import pandas as pd

from app import create_app
from app.extensions import db
from app.models import IMSFact, IMSRawData, IMSSummary, IMSUpload, Product, Representative, Target
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


def test_late_week_is_the_only_fact_snapshot_used_for_monthly_summary():
    app = create_app(DirectUnitTestConfig)
    with app.app_context():
        db.create_all()
        product = Product(product_code="TRAVAZOL", product_name="Travazol", is_active=True)
        representative = Representative(rep_code="WEEKLY-REP", rep_name="WEEKLY REP", active=True)
        db.session.add_all([product, representative])
        db.session.flush()
        week3 = IMSUpload(file_name="3.Hafta.xlsx", year=2032, month=1, week_number=3, status="COMPLETED")
        week5 = IMSUpload(file_name="5.Hafta.xlsx", year=2032, month=1, week_number=5, status="COMPLETED")
        db.session.add_all([week3, week5])
        db.session.flush()
        raw3 = IMSRawData(upload_id=week3.id, year=2032, month=1, quarter="Q1", week_number=3,
                          sheet_name="TTS", sheet_type="brick_sales", source_row=1,
                          representative_id=representative.id, product_id=product.id,
                          representative=representative.rep_name, product=product.product_name, raw_json="{}")
        raw5 = IMSRawData(upload_id=week5.id, year=2032, month=1, quarter="Q1", week_number=5,
                          sheet_name="TTS", sheet_type="brick_sales", source_row=1,
                          representative_id=representative.id, product_id=product.id,
                          representative=representative.rep_name, product=product.product_name, raw_json="{}")
        db.session.add_all([raw3, raw5])
        db.session.flush()
        db.session.add_all([
            IMSFact(upload_id=week3.id, raw_data_id=raw3.id, representative_id=representative.id,
                    product_id=product.id, year=2032, month=1, quarter="Q1", week_number=3,
                    report_type="brick_sales", unit=10, tl=100, metrics_json="{}"),
            IMSFact(upload_id=week5.id, raw_data_id=raw5.id, representative_id=representative.id,
                    product_id=product.id, year=2032, month=1, quarter="Q1", week_number=5,
                    report_type="brick_sales", unit=20, tl=200, metrics_json="{}"),
        ])
        db.session.commit()

        service = IMSImportService("unused.xlsx")
        service.upload = week3
        assert service._is_current_week_snapshot(2032, 1, 3) is False
        service.rebuild_summary(2032, 1)

        summary = IMSSummary.query.one()
        assert summary.tl == 200
        assert summary.unit == 20
