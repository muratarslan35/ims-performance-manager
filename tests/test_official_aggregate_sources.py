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
        self.ctx = self.app.app_context()
        self.ctx.push()
        migrations_dir = str(Path(__file__).resolve().parents[1] / "migrations")
        upgrade(directory=migrations_dir)

        product = Product.query.filter_by(product_code="TRAVAZOL").first()
        if product is None:
            product = Product(product_code="TRAVAZOL", product_name="Travazol", is_active=True)
            db.session.add(product)
        else:
            product.is_active = True
        rep = Representative(
            rep_code="OFFICIAL-REP",
            rep_name="OFFICIAL TEST REP",
            region="901",
            city="DIYARBAKIR",
            active=True,
        )
        db.session.add(rep)
        db.session.flush()
        self.product_id = product.id
        self.rep_id = rep.id
        self.upload = IMSUpload(
            file_name="official.xlsx",
            year=2038,
            month=1,
            quarter="Q1",
            status="COMPLETED",
            completed_at=datetime.utcnow(),
        )
        db.session.add(self.upload)
        db.session.flush()
        self.target = Target(
            year=2038,
            month=1,
            quarter="Q1",
            representative_id=rep.id,
            product_id=product.id,
            tl_target=1005.0,
            unit_target=9999.0,
        )
        self.summary = IMSSummary(
            upload_id=self.upload.id,
            year=2038,
            month=1,
            quarter="Q1",
            representative_id=rep.id,
            product_id=product.id,
            target_tl=1005.0,
            target_unit=9999.0,
        )
        db.session.add_all([self.target, self.summary])
        db.session.commit()
        AliasService.clear()
        AliasService.warmup()

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()
        self.temp_dir.cleanup()

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

    def test_official_national_and_region_targets_ignore_person_target_sum(self):
        service = IMSImportService(Path(self.temp_dir.name) / "official.xlsx")
        service.upload = self.upload
        service.workbook = self._workbook()
        persist_official_aggregates(service, 2038, 1)
        db.session.commit()

        national = OfficialAggregateService.product_totals(2038, 1, "NATIONAL")
        region = OfficialAggregateService.product_totals(2038, 1, "901")
        self.assertEqual(len(national), 1)
        self.assertEqual(len(region), 1)
        self.assertAlmostEqual(national[0]["target_tl"], 1005.0, places=8)
        self.assertAlmostEqual(national[0]["target_unit"], 100.5, places=8)
        self.assertAlmostEqual(region[0]["target_unit"], 100.5, places=8)
        self.assertNotAlmostEqual(national[0]["target_unit"], self.target.unit_target, places=2)

    def test_compact_region_subtotal_rows_are_preserved_and_reconciled(self):
        workbook = self._workbook()
        workbook["BAKİYE"].iat[3, 0] = None
        workbook["TTS HAFTALIK ÇIKIŞLARI"].iat[3, 0] = None

        service = IMSImportService(Path(self.temp_dir.name) / "official.xlsx")
        service.upload = self.upload
        service.workbook = workbook
        result = persist_official_aggregates(service, 2038, 1)
        db.session.commit()

        self.assertTrue(result["reconciliation"]["passed"])
        self.assertEqual(result["reconciliation"]["targets"]["region_count"], 1)
        self.assertEqual(result["reconciliation"]["actuals"]["region_count"], 1)
        region = OfficialAggregateService.product_totals(2038, 1, "901")
        self.assertEqual(len(region), 1)
        self.assertAlmostEqual(region[0]["target_tl"], 1005.0, places=8)
        self.assertAlmostEqual(region[0]["actual_tl"], 250.0, places=8)
        self.assertAlmostEqual(region[0]["actual_unit"], 17.25, places=8)

    def test_compact_tts_subtotals_replace_tl_but_preserve_direct_box_sources(self):
        old_service = IMSImportService(Path(self.temp_dir.name) / "wide.xlsx")
        old_service.upload = self.upload
        old_service.workbook = self._workbook()
        persist_official_aggregates(old_service, 2038, 1)
        db.session.commit()

        compact_upload = IMSUpload(
            file_name="compact.xlsx",
            year=2038,
            month=1,
            quarter="Q1",
            week_number=2,
            status="COMPLETED",
            completed_at=datetime.utcnow(),
        )
        db.session.add(compact_upload)
        db.session.flush()
        compact = {
            "TTS ÇIKIŞLARI": pd.DataFrame([
                [None, "OCAK HEDEF", None, "1-31 OCAK Çıkış", None, "REAL%"],
                [None, None, "TRAVAZOL", None, "TRAVAZOL", None],
                [None, "NATIONAL", 777.0, None, 333.0, None],
                ["901 DIYARBAKIR", "901 DIYARBAKIR", 777.0, None, 333.0, None],
                ["901 DIYARBAKIR", "OFFICIAL TEST REP", 9999.0, None, 9999.0, None],
            ])
        }
        service = IMSImportService(Path(self.temp_dir.name) / "compact.xlsx")
        service.upload = compact_upload
        service.workbook = compact
        result = persist_official_aggregates(service, 2038, 1)
        db.session.commit()

        self.assertTrue(result["reconciliation"]["passed"])
        self.assertEqual(result["reconciliation"]["targets"]["region_count"], 1)
        self.assertEqual(result["reconciliation"]["actuals"]["region_count"], 1)
        region = OfficialAggregateService.product_totals(2038, 1, "901")
        national = OfficialAggregateService.product_totals(2038, 1, "NATIONAL")
        self.assertAlmostEqual(region[0]["target_tl"], 777.0, places=8)
        self.assertAlmostEqual(region[0]["actual_tl"], 333.0, places=8)
        self.assertAlmostEqual(national[0]["target_tl"], 777.0, places=8)
        self.assertAlmostEqual(national[0]["actual_tl"], 333.0, places=8)
        self.assertAlmostEqual(region[0]["target_unit"], 100.5, places=8)
        self.assertAlmostEqual(region[0]["actual_unit"], 17.25, places=8)

    def test_dashboard_uses_official_box_target_and_direct_box_actual(self):
        service = IMSImportService(Path(self.temp_dir.name) / "official.xlsx")
        service.upload = self.upload
        service.workbook = self._workbook()
        persist_official_aggregates(service, 2038, 1)
        db.session.commit()

        metrics = DashboardQuery().load_national_dashboard_metrics(DashboardFilterParams(year=2038, month=1))
        self.assertEqual(metrics["target_tl"], 1005.0)
        self.assertEqual(metrics["unit_target"], 100.5)
        self.assertEqual(metrics["actual_tl"], 250.0)
        self.assertEqual(metrics["unit_actual"], 17.25)
        regions = DashboardQuery().load_region_performance(DashboardFilterParams(year=2038, month=1))
        self.assertEqual(len(regions), 1)
        self.assertAlmostEqual(float(regions[0].unit_target), 100.5, places=8)
        self.assertAlmostEqual(float(regions[0].unit_actual), 17.25, places=8)

    def test_vacant_target_rows_remain_valid_and_exact_units_are_not_rounded(self):
        vacancy = Representative(
            rep_code="VAC-901",
            rep_name="DIYARBAKIR BOS",
            region="901",
            active=False,
        )
        db.session.add(vacancy)
        db.session.commit()
        AliasService.clear()
        AliasService.warmup()

        service = TargetImportService("unused.xlsx", self.upload.id, workbook={})
        self.assertTrue(service._is_probable_representative_name("DIYARBAKIR BOS"))
        match = service._resolve_representative_match("DIYARBAKIR BOS")
        self.assertTrue(match["matched"])
        target_map = {}
        pending = []
        service._upsert_target(
            target_map,
            pending,
            vacancy.id,
            self.product_id,
            2038,
            1,
            "Q1",
            123.4567,
            999.0,
        )
        self.assertAlmostEqual(pending[0].unit_target, 123.4567, places=8)


if __name__ == "__main__":
    unittest.main()
