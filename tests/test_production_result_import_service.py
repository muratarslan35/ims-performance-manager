from pathlib import Path

from openpyxl import Workbook

from app import create_app
from app.extensions import db
from app.models import Product, ProductionResultUpload, Representative
from app.services.production_result_import_service import ProductionResultImportService


class ProductionImportConfig:
    TESTING = True
    SECRET_KEY = "production-import-test"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = Path("/tmp/production-import-uploads")
    REPORT_FOLDER = Path("/tmp/production-import-reports")
    BACKUP_FOLDER = Path("/tmp/production-import-backups")
    LOG_FOLDER = Path("/tmp/production-import-logs")


def test_production_workbook_applies_only_final_percentages(tmp_path):
    path = tmp_path / "ocak-uretim.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "OCAK REAL%"
    sheet.append(["REAL%", "TRAVAZOL", "MONUROL", "TOPLAM"])
    sheet.append(["NATIONAL", 100, 100, 100])
    sheet.append(["MURAT ARSLAN", 121.96, 95, 110])
    workbook.save(path)

    app = create_app(ProductionImportConfig)
    with app.app_context():
        db.create_all()
        representative = Representative(rep_code="MURAT", rep_name="MURAT ARSLAN", active=True)
        travazol = Product(product_code="TRAVAZOL", product_name="Travazol", is_active=True)
        monurol = Product(product_code="MONUROL", product_name="Monurol", is_active=True)
        db.session.add_all([representative, travazol, monurol])
        db.session.flush()
        upload = ProductionResultUpload(
            file_name=path.name, stored_file_name=path.name, source_hash="x" * 64,
            year=2026, month=1, production_stage=2,
        )
        db.session.add(upload)
        db.session.flush()

        report = ProductionResultImportService(path).parse()
        ProductionResultImportService.apply(upload, report)
        db.session.commit()

        assert upload.status == ProductionResultUpload.STATUS_APPLIED
        assert upload.matched_row_count == 2
        assert upload.product_results.count() == 2
        assert upload.representative_totals.count() == 1
