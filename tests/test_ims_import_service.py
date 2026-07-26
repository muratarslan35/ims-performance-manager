import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app import create_app
from app.extensions import db
from app.models import IMSFact, IMSRawData, IMSSummary, Product, Representative
from app.services.alias_service import AliasService
from app.services.ims_import_service import IMSImportService


class IMSEtlTestConfig:
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = Path(tempfile.gettempdir()) / "ims-test-uploads"
    REPORT_FOLDER = Path(tempfile.gettempdir()) / "ims-test-reports"
    BACKUP_FOLDER = Path(tempfile.gettempdir()) / "ims-test-backups"
    LOG_FOLDER = Path(tempfile.gettempdir()) / "ims-test-logs"


class IMSImportServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(IMSEtlTestConfig)
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        db.session.add_all(
            [
                Representative(rep_code="R-001", rep_name="Ayşe Kaya", active=True),
                Product(product_code="TRAVAZOL", product_name="Travazol", is_active=True),
            ]
        )
        db.session.commit()
        AliasService.clear()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def test_import_builds_raw_facts_and_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            workbook_path = Path(directory) / "ims.xlsx"
            pd.DataFrame(
                [
                    ["IMS Performans Raporu", None, None],
                    ["Representative", "Travazol Box", "Travazol TL"],
                    ["Ayşe Kaya", 12, 300.5],
                ]
            ).to_excel(workbook_path, index=False, header=False, sheet_name="BRICK SATIS")

            result = IMSImportService(workbook_path, uploaded_by="Test User").run(2026, 1)

        self.assertTrue(result["success"], result["errors"])
        self.assertEqual(IMSRawData.query.count(), 1)
        self.assertEqual(IMSFact.query.count(), 1)
        self.assertEqual(IMSSummary.query.count(), 1)

        summary = IMSSummary.query.one()
        self.assertEqual(summary.unit, 12)
        self.assertEqual(summary.tl, 300.5)
        self.assertEqual(summary.year, 2026)
        self.assertEqual(summary.month, 1)


if __name__ == "__main__":
    unittest.main()
