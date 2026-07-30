import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app import create_app
from app.extensions import db
from app.models import (
    IMSFact,
    IMSRawData,
    IMSSummary,
    ImportAuditLog,
    ManualMatchQueue,
    Product,
    Representative,
    RepresentativeMatch,
)
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

    def _make_workbook(self, directory, filename="ims.xlsx"):
        workbook_path = Path(directory) / filename
        pd.DataFrame(
            [
                ["IMS Performans Raporu", None, None],
                ["Representative", "Travazol Box", "Travazol TL"],
                ["Ayşe Kaya", 12, 300.5],
            ]
        ).to_excel(workbook_path, index=False, header=False, sheet_name="BRICK SATIS")
        return workbook_path

    def test_import_builds_raw_facts_and_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            workbook_path = self._make_workbook(directory)
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

    def test_week_number_extracted_from_filename(self):
        """Week number is parsed from the file name (e.g. '24.Hafta')."""
        with tempfile.TemporaryDirectory() as directory:
            workbook_path = self._make_workbook(directory, "24.Hafta Haziran IMS.xlsx")
            result = IMSImportService(workbook_path, uploaded_by="Test User").run(2026, 6)

        self.assertTrue(result["success"], result["errors"])
        fact = IMSFact.query.one()
        self.assertEqual(fact.week_number, 24)

    def test_idempotent_weekly_reimport(self):
        """Re-importing the same week updates existing facts without duplicates."""
        with tempfile.TemporaryDirectory() as directory:
            workbook_path = self._make_workbook(directory, "24.Hafta IMS.xlsx")
            IMSImportService(workbook_path, uploaded_by="User1").run(2026, 6)
            self.assertEqual(IMSFact.query.count(), 1)

            # Re-import same week with updated values
            workbook_path2 = Path(directory) / "24.Hafta IMS v2.xlsx"
            pd.DataFrame(
                [
                    ["IMS Performans Raporu", None, None],
                    ["Representative", "Travazol Box", "Travazol TL"],
                    ["Ayşe Kaya", 20, 500.0],
                ]
            ).to_excel(workbook_path2, index=False, header=False, sheet_name="BRICK SATIS")
            IMSImportService(workbook_path2, uploaded_by="User2").run(2026, 6)

        self.assertEqual(IMSFact.query.count(), 1, "Re-import must not duplicate facts")
        fact = IMSFact.query.one()
        self.assertEqual(fact.unit, 20, "Fact values should be updated on re-import")
        self.assertEqual(fact.tl, 500.0)

    def test_unmatched_rep_queued_for_manual(self):
        """An unrecognised representative name creates a ManualMatchQueue entry."""
        with tempfile.TemporaryDirectory() as directory:
            workbook_path = Path(directory) / "ims.xlsx"
            pd.DataFrame(
                [
                    ["IMS Performans Raporu", None, None],
                    ["Representative", "Travazol Box", "Travazol TL"],
                    ["Unknown Rep XYZ", 5, 100.0],
                ]
            ).to_excel(workbook_path, index=False, header=False, sheet_name="BRICK SATIS")
            IMSImportService(workbook_path, uploaded_by="Test User").run(2026, 1)

        queue_items = ManualMatchQueue.query.filter_by(
            entity_type=ManualMatchQueue.ENTITY_REPRESENTATIVE
        ).all()
        self.assertEqual(len(queue_items), 1)
        self.assertEqual(queue_items[0].ims_name, "Unknown Rep XYZ")
        self.assertEqual(queue_items[0].status, ManualMatchQueue.STATUS_PENDING)

    def test_import_audit_log_created(self):
        """An ImportAuditLog record is created for every successful import."""
        with tempfile.TemporaryDirectory() as directory:
            workbook_path = self._make_workbook(directory)
            IMSImportService(workbook_path, uploaded_by="Test User").run(2026, 1)

        self.assertEqual(ImportAuditLog.query.count(), 1)
        audit = ImportAuditLog.query.one()
        self.assertEqual(audit.status, "COMPLETED")
        self.assertEqual(audit.uploaded_by, "Test User")

    def test_persistent_match_used_in_next_import(self):
        """A persisted RepresentativeMatch is resolved automatically in subsequent imports."""
        rep = Representative.query.first()
        AliasService.persist_representative_match(
            ims_name="Custom Rep Name",
            representative=rep,
            method="MANUAL",
            score=100.0,
        )
        db.session.commit()
        AliasService.refresh()

        with tempfile.TemporaryDirectory() as directory:
            workbook_path = Path(directory) / "ims.xlsx"
            pd.DataFrame(
                [
                    ["IMS Performans Raporu", None, None],
                    ["Representative", "Travazol Box", "Travazol TL"],
                    ["Custom Rep Name", 8, 200.0],
                ]
            ).to_excel(workbook_path, index=False, header=False, sheet_name="BRICK SATIS")
            result = IMSImportService(workbook_path, uploaded_by="Test User").run(2026, 2)

        self.assertTrue(result["success"], result["errors"])
        self.assertEqual(result["statistics"]["unmatched_representatives"], 0)
        self.assertEqual(IMSFact.query.count(), 1)

    def test_match_priority_match_table_beats_alias(self):
        """Match table (priority 1) overrides alias lookup (priority 4)."""
        rep = Representative.query.first()
        # Create a conflicting alias pointing to the same rep
        AliasService.create_representative_alias(rep, "Ayse Kaya Alias")
        # Create a match table entry for the same normalized string
        AliasService.persist_representative_match(
            ims_name="Match Table Name",
            representative=rep,
            method="MANUAL",
            score=100.0,
        )
        db.session.commit()
        AliasService.refresh()

        result = AliasService.find_representative("Match Table Name")
        self.assertTrue(result["matched"])
        self.assertEqual(result["method"], "MATCH_TABLE")


if __name__ == "__main__":
    unittest.main()
