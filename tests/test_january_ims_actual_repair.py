from pathlib import Path
import tempfile

from openpyxl import Workbook

from app import create_app
from app.extensions import db
from app.models import IMSUpload, IMSSummary, Product, Representative, Target
from app.services.ims_import_service import IMSImportService
from repair_january_ims_actuals import PRODUCT_CODES, extract_weekly_actuals, repair_period


class RepairTestConfig:
    TESTING = True
    SECRET_KEY = "january-actual-repair-test"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = Path(tempfile.gettempdir()) / "january-repair-uploads"
    REPORT_FOLDER = Path(tempfile.gettempdir()) / "january-repair-reports"
    BACKUP_FOLDER = Path(tempfile.gettempdir()) / "january-repair-backups"
    LOG_FOLDER = Path(tempfile.gettempdir()) / "january-repair-logs"


def build_weekly_workbook(path: Path):
    wb = Workbook()
    ws = wb.active
    ws.title = "TTS HAFTALIK ÇIKIŞLARI"

    # First cumulative TL block followed by first cumulative KUTU block.
    row1 = [None, None] + [None] * 14
    row1[2] = "1-18 OCAK TL ÇIKIŞI"
    row1[9] = "1-18 OCAK KUTU ÇIKIŞI"
    ws.append(row1)
    ws.append([None, None, *PRODUCT_CODES, *PRODUCT_CODES])

    def row(location, representative, base):
        tl = [base + index * 10 for index in range(7)]
        unit = [base / 10 + index for index in range(7)]
        return [location, representative, *tl, *unit]

    ws.append(row(None, "NATIONAL", 9000))
    ws.append(row("901 TEST", "901 TEST", 8000))
    ws.append(row("901 TEST", "GERCEK TEMSILCI", 100))
    ws.append(row("901 TEST", "TEST BOS BRICK", 200))
    wb.save(path)
    wb.close()


def test_extract_weekly_actuals_uses_explicit_tl_and_unit_blocks(tmp_path):
    source = tmp_path / "weekly.xlsx"
    build_weekly_workbook(source)

    records = extract_weekly_actuals(source)
    assert len(records) == 2
    by_name = {row["representative"]: row for row in records}
    assert by_name["GERCEK TEMSILCI"]["values"]["TRAVAZOL"] == {"tl": 100.0, "unit": 10.0}
    assert by_name["GERCEK TEMSILCI"]["values"]["BRIMODER"] == {"tl": 160.0, "unit": 16.0}
    assert by_name["TEST BOS BRICK"]["values"]["MONUROL"] == {"tl": 210.0, "unit": 21.0}


def test_repair_updates_only_actuals_and_resolves_vacant_cadre(monkeypatch, tmp_path):
    source = tmp_path / "weekly.xlsx"
    build_weekly_workbook(source)
    app = create_app(RepairTestConfig)

    with app.app_context():
        db.create_all()
        products = {}
        for index, code in enumerate(PRODUCT_CODES, start=1):
            product = Product(product_code=code, product_name=code.title(), is_active=True)
            db.session.add(product)
            products[code] = product
        real = Representative(rep_code="REAL", rep_name="GERCEK TEMSILCI", region="901", city="Test", active=True)
        vacant = Representative(rep_code="VAC", rep_name="TEST BOS KADRO", region="901", city="Test", active=False)
        db.session.add_all([real, vacant])
        db.session.flush()

        upload = IMSUpload(file_name=source.name, year=2026, month=1, quarter="Q1", status="COMPLETED")
        db.session.add(upload)
        db.session.flush()
        for rep in (real, vacant):
            for index, code in enumerate(PRODUCT_CODES, start=1):
                target = Target(
                    year=2026, month=1, quarter="Q1", representative_id=rep.id,
                    product_id=products[code].id, tl_target=1000 + index,
                    unit_target=50 + index, tl_realization=999, unit_realization=999,
                )
                summary = IMSSummary(
                    upload_id=upload.id, year=2026, month=1, quarter="Q1",
                    representative_id=rep.id, product_id=products[code].id,
                    tl=999, unit=999, target_tl=1000 + index, target_unit=50 + index,
                )
                db.session.add_all([target, summary])
        db.session.commit()

        target_before = {
            (row.representative_id, row.product_id): (row.tl_target, row.unit_target)
            for row in Target.query.filter_by(year=2026, month=1).all()
        }

        monkeypatch.setattr(IMSImportService, "load_workbook", lambda self, *args, **kwargs: setattr(self, "workbook", {}))
        monkeypatch.setattr(IMSImportService, "persist_national_dashboard_metrics", lambda self, year, month: None)

        result = repair_period(year=2026, month=1, source_file=source)
        assert result["representatives"] == 2
        assert result["products"] == 7
        assert result["touched"] == 14
        assert result["target_rows"] == 14
        assert result["summary_rows"] == 14

        target_after = {
            (row.representative_id, row.product_id): (row.tl_target, row.unit_target)
            for row in Target.query.filter_by(year=2026, month=1).all()
        }
        assert target_after == target_before

        real_trav = IMSSummary.query.filter_by(
            year=2026, month=1, representative_id=real.id, product_id=products["TRAVAZOL"].id
        ).one()
        vacant_mon = IMSSummary.query.filter_by(
            year=2026, month=1, representative_id=vacant.id, product_id=products["MONUROL"].id
        ).one()
        assert (real_trav.tl, real_trav.unit) == (100.0, 10.0)
        assert (vacant_mon.tl, vacant_mon.unit) == (210.0, 21.0)

        target_real = Target.query.filter_by(
            year=2026, month=1, representative_id=real.id, product_id=products["TRAVAZOL"].id
        ).one()
        assert target_real.tl_realization == 100.0
        assert target_real.unit_realization == 10.0
