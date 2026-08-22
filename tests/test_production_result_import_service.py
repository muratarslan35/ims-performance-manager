from pathlib import Path

from openpyxl import Workbook

from app import create_app
from app.extensions import db
from app.models import Product, ProductionResultUpload, Representative, Target
from app.services.production_result_import_service import ProductionResultImportService
from app.services.production_result_service import ProductionResultService


class ProductionImportConfig:
    TESTING = True
    SECRET_KEY = "production-import-test"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = Path("/tmp/production-import-uploads")
    REPORT_FOLDER = Path("/tmp/production-import-reports")
    BACKUP_FOLDER = Path("/tmp/production-import-backups")
    LOG_FOLDER = Path("/tmp/production-import-logs")


PRODUCTS = ["TRAVAZOL", "MONUROL", "MIXOVUL", "FENTIVAG", "STIDERM", "ACNEMIX", "BRIMODER"]


def _sheet(workbook, title, metric, values, percentages, total_actual, total_percent, with_stage):
    sheet = workbook.create_sheet(title)
    header = ["BOLGE", "TEMSILCI", ""] + PRODUCTS + [f"{metric} HEDEF", "", ""]
    header += PRODUCTS + [f"{metric} CIKIS", "", ""] + PRODUCTS + ["REA"]
    if with_stage:
        header += ["HAFTALIK", "1 URETIM", "2 URETIM"]
    sheet.append(header)
    # KOTA SATIŞ uses column A for sicil, B for region and C for the name.
    row = ["", "901 DIYARBAKIR", "MURAT ARSLAN"] + [100] * 7 + [700, "", ""]
    row += values + [total_actual, "", ""] + percentages + [total_percent]
    if with_stage:
        row += [100, 110, total_percent]
    sheet.append(row)
    return sheet


def test_kota_workbook_preserves_exact_tl_and_unit_results(tmp_path):
    path = tmp_path / "ocak-uretim.xlsx"
    workbook = Workbook()
    workbook.remove(workbook.active)
    _sheet(workbook, "TTS REALIZASYONLARI TL", "TL", [120] * 7, [120] * 7, 840, 120, True)
    # Approved KUTU files may not carry production-stage columns. REA is final.
    _sheet(workbook, "TTS REALIZASYONLARI KUTU", "KUTU", [11] * 7, [110] * 7, 77, 110, False)
    workbook.save(path)

    app = create_app(ProductionImportConfig)
    with app.app_context():
        db.create_all()
        # The factory may seed reference targets; this fixture deliberately
        # defines the complete period scope that the strict importer validates.
        db.session.query(Target).delete()
        representative = Representative(rep_code="MURAT", rep_name="MURAT ARSLAN", region="901 DIYARBAKIR", active=True)
        db.session.add(representative)
        db.session.flush()
        products = []
        for name in PRODUCTS:
            product = Product.query.filter_by(product_code=name).first()
            if product is None:
                product = Product(product_code=name, product_name=name.title(), is_active=True)
                db.session.add(product)
            products.append(product)
        db.session.flush()
        db.session.add_all([
            Target(year=2026, month=1, representative_id=representative.id, product_id=product.id, tl_target=100, unit_target=10)
            for product in products
        ])
        upload = ProductionResultUpload(
            file_name=path.name, stored_file_name=path.name, source_hash="x" * 64,
            year=2026, month=1, production_stage=2,
        )
        db.session.add(upload)
        db.session.flush()

        report = ProductionResultImportService(path, 2026, 1).parse()
        ProductionResultImportService.apply(upload, report)
        db.session.commit()

        assert upload.status == ProductionResultUpload.STATUS_APPLIED
        assert upload.matched_row_count == 7
        result = ProductionResultService.effective_product(2026, 1, representative.id, products[0].id)
        assert result["actual_tl"] == 120
        assert result["actual_unit"] == 11
        assert result["target_tl"] == 100
        assert result["target_unit"] == 10
        assert result["realization_percent"] == 120
