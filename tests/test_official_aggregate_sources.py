import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd
from flask_migrate import upgrade

from app import create_app
from app.extensions import db
from app.models import IMSSummary, IMSUpload, Product, Representative, Target
from app.query.dashboard_query import DashboardQuery
from app.query.filters import DashboardFilterParams
from app.services.alias_service import AliasService
from app.services.ims_import_service import IMSImportService
from app.services.official_aggregate_service import OfficialAggregateService, persist_official_aggregates
from app.services.region_performance_service import RegionPerformanceService
from app.services.target_import_service import TargetImportService


class Config:
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = Path(tempfile.gettempdir()) / "official-aggregate-test-uploads"
    REPORT_FOLDER = Path(tempfile.gettempdir()) / "official-aggregate-test-reports"
    BACKUP_FOLDER = Path(tempfile.gettempdir()) / "official-aggregate-test-backups"
    LOG_FOLDER = Path(tempfile.gettempdir()) / "official-aggregate-test-logs"


class OfficialAggregateSourceTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "official.db"
        config = type("RuntimeConfig", (Config,), {"SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}"})
        self.app = create_app(config)
        self.ctx = self.app.app_context(); self.ctx.push()
        migrations_dir = str(Path(__file__).resolve().parents[1] / "migrations")
        upgrade(directory=migrations_dir)
        product = Product.query.filter_by(product_code="TRAVAZOL").first()
        if product is None:
            product = Product(product_code="TRAVAZOL", product_name="Travazol", is_active=True)
            db.session.add(product)
        else:
            product.is_active = True
        rep = Representative(rep_code="OFFICIAL-REP", rep_name="OFFICIAL TEST REP", region="901", city="DIYARBAKIR", active=True)
        db.session.add(rep); db.session.flush()
        self.product_id = product.id; self.rep_id = rep.id
        self.upload = IMSUpload(file_name="official.xlsx", year=2038, month=1, quarter="Q1", status="COMPLETED", completed_at=datetime.utcnow())
        db.session.add(self.upload); db.session.flush()
        self.target = Target(year=2038, month=1, quarter="Q1", representative_id=rep.id, product_id=product.id, tl_target=1005.0, unit_target=1.0)
        self.summary = IMSSummary(year=2038, month=1, quarter="Q1", representative_id=rep.id, product_id=product.id, target_tl=1005.0, target_unit=1.0)
        db.session.add_all([self.target, self.summary]); db.session.commit()
        AliasService.clear(); AliasService.warmup()

    def tearDown(self):
        db.session.remove(); self.ctx.pop(); self.temp_dir.cleanup()

    def _workbook(self):
        return {
            "BAKİYE": pd.DataFrame([
                [None, None, None, None, None, None, None, None, None, None, None, None],
                [None, "OCAK HEDEF TL", "TRAVAZOL", None, "OCAK ÇIKIŞ TL", "TRAVAZOL", None, "OCAK TL BAKİYE", "TRAVAZOL", None, "OCAK MF siz KUTU BAKİYE", "TRAVAZOL"],
                [None, "NATIONAL", 1005.0, None, "NATIONAL", 250.0, None, "NATIONAL", 600.0, None, "NATIONAL", 60.0],
                ["901 DIYARBAKIR", "901 DIYARBAKIR", 1005.0, None, "901 DIYARBAKIR", 250.0, None, "901 DIYARBAKIR", 600.0, None, "901 DIYARBAKIR", 60.0],
                ["901 DIYARBAKIR", "OFFICIAL TEST REP", 1005.0, None, "OFFICIAL TEST REP", 250.0, None, "OFFICIAL TEST REP", 600.0, None, "OFFICIAL TEST REP", 60.0],
            ]),
            "TTS HAFTALIK ÇIKIŞLARI": pd.DataFrame([
                [None, None, "1-18 OCAK TL ÇIKIŞI", None, "1-18 OCAK KUTU ÇIKIŞI", None],
                [None, None, None, "TRAVAZOL", None, "TRAVAZOL"],
                [None, "NATIONAL", None, 250.0, None, 17.25],
                ["901 DIYARBAKIR", "901 DIYARBAKIR", None, 250.0, None, 17.25],
                ["901 DIYARBAKIR", "OFFICIAL TEST REP", None, 250.0, None, 17.25],
            ]),
        }

    def test_exact_unit_sources_and_official_aggregates(self):
        service = IMSImportService(Path(self.temp_dir.name) / "official.xlsx")
        service.upload = self.upload
        service.workbook = self._workbook()
        service.apply_balance_summary(2038, 1)
        service.apply_weekly_sales_summary(2038, 1)
        persist_official_aggregates(service, 2038, 1)
        db.session.commit()

        target = db.session.get(Target, self.target.id)
        summary = db.session.get(IMSSummary, self.summary.id)
        self.assertAlmostEqual(target.unit_target, 100.5, places=8)
        self.assertAlmostEqual(target.unit_realization, 17.25, places=8)
        self.assertAlmostEqual(summary.unit, 17.25, places=8)
        self.assertAlmostEqual(target.tl_realization, 250.0, places=8)

        national = OfficialAggregateService.product_totals(2038, 1, "NATIONAL")
        region = OfficialAggregateService.product_totals(2038, 1, "901")
        self.assertEqual(len(national), 1); self.assertEqual(len(region), 1)
        self.assertAlmostEqual(national[0]["target_unit"], 100.5, places=8)
        self.assertAlmostEqual(region[0]["target_unit"], 100.5, places=8)
        self.assertAlmostEqual(national[0]["actual_unit"], 17.25, places=8)

    def test_dashboard_and_region_use_official_aggregates(self):
        service = IMSImportService(Path(self.temp_dir.name) / "official.xlsx")
        service.upload = self.upload; service.workbook = self._workbook()
        persist_official_aggregates(service, 2038, 1); db.session.commit()

        filters = DashboardFilterParams(year=2038, month=1)
        national = DashboardQuery().load_national_dashboard_metrics(filters)
        self.assertEqual(national["target_tl"], 1005.0)
        self.assertEqual(national["unit_target"], 100.5)
        self.assertEqual(national["actual_tl"], 250.0)
        self.assertEqual(national["unit_actual"], 17.25)
        region_rows = DashboardQuery().load_region_performance(filters)
        self.assertEqual(len(region_rows), 1)
        self.assertAlmostEqual(float(region_rows[0].unit_target), 100.5, places=8)
        report = RegionPerformanceService("901", 2038, 1).report()["periods"]["monthly"]
        self.assertAlmostEqual(float(report["target_tl"]), 1005.0, places=8)
        self.assertAlmostEqual(float(report["target_unit"]), 100.5, places=8)
        self.assertAlmostEqual(float(report["actual_unit"]), 17.25, places=8)

    def test_vacant_target_rows_are_valid_and_exact_units_are_not_rounded(self):
        vacancy = Representative(rep_code="VAC-901", rep_name="DIYARBAKIR BOS", region="901", active=False)
        db.session.add(vacancy); db.session.commit(); AliasService.clear(); AliasService.warmup()
        service = TargetImportService("unused.xlsx", self.upload.id, workbook={})
        self.assertTrue(service._is_probable_representative_name("DIYARBAKIR BOS"))
        match = service._resolve_representative_match("DIYARBAKIR BOS")
        self.assertTrue(match["matched"])
        target_map = {}; pending = []
        service._upsert_target(target_map, pending, vacancy.id, self.product_id, 2038, 1, "Q1", 123.4567, 999.0)
        self.assertAlmostEqual(pending[0].unit_target, 123.4567, places=8)


if __name__ == "__main__":
    unittest.main()
