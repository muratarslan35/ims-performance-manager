import tempfile
import unittest
from pathlib import Path

import pandas as pd
from flask_migrate import upgrade

from app import create_app
from app.extensions import db
from app.models import IMSFact, IMSSummary, IMSUpload, Product, Representative, Target
from app.services.alias_service import AliasService
from app.services.compact_tts_import_actual_authority import apply_compact_tts_representative_actuals
from app.services.ims_import_service import IMSImportService


class Config:
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = Path(tempfile.gettempdir()) / "compact-tts-actual-uploads"
    REPORT_FOLDER = Path(tempfile.gettempdir()) / "compact-tts-actual-reports"
    BACKUP_FOLDER = Path(tempfile.gettempdir()) / "compact-tts-actual-backups"
    LOG_FOLDER = Path(tempfile.gettempdir()) / "compact-tts-actual-logs"


class CompactTTSActualAuthorityTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "compact.db"
        config = type("RuntimeConfig", (Config,), {"SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}"})
        self.app = create_app(config)
        self.ctx = self.app.app_context()
        self.ctx.push()
        migrations_dir = str(Path(__file__).resolve().parents[1] / "migrations")
        upgrade(directory=migrations_dir)

        self.products = []
        for code, name in (("TRAVAZOL", "Travazol"), ("MONUROL", "Monurol")):
            product = Product.query.filter_by(product_code=code).first()
            if product is None:
                product = Product(product_code=code, product_name=name, is_active=True)
                db.session.add(product)
            else:
                product.is_active = True
            self.products.append(product)
        db.session.flush()

        self.rep = Representative(
            rep_code="COMPACT-REP",
            rep_name="COMPACT TEST REP",
            region="901",
            city="DIYARBAKIR",
            active=True,
        )
        db.session.add(self.rep)
        db.session.flush()
        self.upload = IMSUpload(
            file_name="14.Hafta compact.xlsx",
            year=2039,
            month=3,
            week_number=14,
            quarter="Q1",
            status="PROCESSING",
        )
        db.session.add(self.upload)
        db.session.flush()

        for product, target_tl, brick_tl in zip(self.products, (100.0, 200.0), (10.0, 20.0)):
            target = Target(
                year=2039,
                month=3,
                quarter="Q1",
                representative_id=self.rep.id,
                product_id=product.id,
                tl_target=target_tl,
                unit_target=10.0,
                tl_realization=brick_tl,
            )
            summary = IMSSummary(
                upload_id=self.upload.id,
                year=2039,
                month=3,
                quarter="Q1",
                representative_id=self.rep.id,
                product_id=product.id,
                target_tl=target_tl,
                target_unit=10.0,
                tl=brick_tl,
                unit=5.0,
            )
            fact = IMSFact(
                upload_id=self.upload.id,
                representative_id=self.rep.id,
                product_id=product.id,
                year=2039,
                month=3,
                week_number=14,
                quarter="Q1",
                report_type="brick_sales",
                tl=brick_tl,
                unit=5.0,
            )
            db.session.add_all([target, summary, fact])
        db.session.commit()
        AliasService.clear()
        AliasService.warmup()

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()
        self.temp_dir.cleanup()

    def _compact_frame(self):
        return pd.DataFrame([
            [None, "MART HEDEF", None, None, None, None, None, None, None, None, None, None, None],
            [None, None, "TRAVAZOL", "MONUROL", "TOPLAM", None, "TRAVAZOL", "MONUROL", "TOPLAM", None, "TRAVAZOL", "MONUROL", "TOPLAM"],
            [None, "NATIONAL", 100, 200, 300, None, 999, 999, 1998, None, 999, 999, 999],
            ["901 DIYARBAKIR", "901 DIYARBAKIR", 100, 200, 300, None, 999, 999, 1998, None, 999, 999, 999],
            ["901 DIYARBAKIR", "COMPACT TEST REP", 100, 200, 300, None, 120, 0, 120, None, 120, 0, 40],
        ])

    def test_direct_compact_actual_overrides_summary_and_preserves_numeric_zero(self):
        service = IMSImportService("unused.xlsx")
        service.upload = self.upload
        service.workbook = {"TTS ÇIKIŞLARI": self._compact_frame(), "1001 BRICK SATIS": pd.DataFrame([[1]])}

        fact_before = {(row.product_id, row.tl, row.unit) for row in IMSFact.query.filter_by(upload_id=self.upload.id).all()}
        result = apply_compact_tts_representative_actuals(service, 2039, 3)
        db.session.commit()

        self.assertEqual(result["source"], "compact_tts_direct_actual")
        self.assertEqual(result["matched_representatives"], 1)
        self.assertEqual(result["updated_values"], 2)
        summaries = {row.product_id: row for row in IMSSummary.query.filter_by(upload_id=self.upload.id).all()}
        targets = {row.product_id: row for row in Target.query.filter_by(year=2039, month=3, representative_id=self.rep.id).all()}
        self.assertAlmostEqual(summaries[self.products[0].id].tl, 120.0)
        self.assertAlmostEqual(summaries[self.products[1].id].tl, 0.0)
        self.assertAlmostEqual(summaries[self.products[0].id].realization_percent, 120.0)
        self.assertAlmostEqual(summaries[self.products[1].id].realization_percent, 0.0)
        self.assertAlmostEqual(targets[self.products[0].id].tl_realization, 120.0)
        self.assertAlmostEqual(targets[self.products[1].id].tl_realization, 0.0)
        fact_after = {(row.product_id, row.tl, row.unit) for row in IMSFact.query.filter_by(upload_id=self.upload.id).all()}
        self.assertEqual(fact_before, fact_after)

    def test_wide_weekly_layout_is_not_claimed_by_compact_fallback(self):
        service = IMSImportService("unused.xlsx")
        service.upload = self.upload
        service.workbook = {
            "TTS HAFTALIK ÇIKIŞLARI": pd.DataFrame([
                [None, "1-31 MART TL ÇIKIŞI", None],
                [None, "TRAVAZOL", "MONUROL"],
                ["COMPACT TEST REP", 120, 80],
            ])
        }
        result = apply_compact_tts_representative_actuals(service, 2039, 3)
        self.assertEqual(result["updated_values"], 0)
        self.assertEqual(result["source"], "unavailable")


if __name__ == "__main__":
    unittest.main()
