import tempfile
import unittest
import json
from pathlib import Path
from unittest import mock

import pandas as pd
from openpyxl import Workbook

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

    def _make_brick_analysis_workbook(self, directory, filename="brick_analysis.xlsx"):
        workbook_path = Path(directory) / filename
        sheets = {
            "TL": [
                ["Bilim İlaç Brick Analizi", None, None, None, None],
                ["Coğrafya", "Coğrafya", "Saha", "Ürün", "Metrik"],
                ["Bölge", "İl", "Temsilci", "Ürün Grubu", "TL"],
                ["Marmara", "İstanbul", "Ayşe Kaya", "Travazol", 300.5],
                ["Marmara", "İstanbul", "Ayşe Kaya", "", 10],
            ],
            "BOX": [
                ["Bilim İlaç Brick Analizi", None, None, None, None],
                ["Coğrafya", "Coğrafya", "Saha", "Ürün", "Metrik"],
                ["Bölge", "İl", "Temsilci", "Ürün Grubu", "Kutu"],
                ["Marmara", "İstanbul", "Ayşe Kaya", "Travazol", 12],
            ],
            "MARKET": [
                ["Bilim İlaç Brick Analizi", None, None, None, None],
                ["Coğrafya", "Coğrafya", "Saha", "Ürün", "Metrik"],
                ["Bölge", "İl", "Temsilci", "Ürün Grubu", "Pazar Payı"],
                ["Marmara", "İstanbul", "Ayşe Kaya", "Travazol", 4.2],
            ],
        }
        with pd.ExcelWriter(workbook_path) as writer:
            for sheet_name, rows in sheets.items():
                pd.DataFrame(rows).to_excel(writer, index=False, header=False, sheet_name=sheet_name)
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

    def test_brick_analysis_multi_sheet_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            workbook_path = self._make_brick_analysis_workbook(directory)
            result = IMSImportService(workbook_path, uploaded_by="Test User").run(2026, 3)

        self.assertTrue(result["success"], result["errors"])
        self.assertEqual(IMSRawData.query.count(), 1)
        self.assertEqual(IMSFact.query.count(), 1)
        self.assertEqual(IMSSummary.query.count(), 1)

        fact = IMSFact.query.one()
        self.assertEqual(fact.unit, 12)
        self.assertEqual(fact.tl, 300.5)
        self.assertEqual(fact.market_share, 4.2)

        raw = IMSRawData.query.one()
        payload = json.loads(raw.raw_json)
        self.assertEqual(payload["source_values"]["region"], "Marmara")
        self.assertEqual(payload["source_values"]["province"], "İstanbul")
        self.assertEqual(payload["source_values"]["product_group"], "Travazol")

        reasons = {item["reason"] for item in result["skipped_logs"]}
        self.assertIn("missing_product_group", reasons)

    def test_wide_mode_representative_match_memoized_per_import(self):
        with tempfile.TemporaryDirectory() as directory:
            workbook_path = Path(directory) / "ims-memo-wide.xlsx"
            pd.DataFrame(
                [
                    ["IMS Performans Raporu", None, None],
                    ["Representative", "Travazol Box", "Travazol TL"],
                    ["Ayşe Kaya", 12, 300.5],
                    ["Ayşe Kaya", 10, 200.0],
                ]
            ).to_excel(workbook_path, index=False, header=False, sheet_name="BRICK SATIS")

            service = IMSImportService(workbook_path, uploaded_by="Test User")
            with mock.patch.object(
                AliasService, "find_representative", wraps=AliasService.find_representative
            ) as find_representative:
                result = service.run(2026, 4)

        self.assertTrue(result["success"], result["errors"])
        self.assertEqual(find_representative.call_count, 1)
        self.assertEqual(IMSRawData.query.count(), 2)

    def test_normalized_mode_product_match_memoized_per_import(self):
        with tempfile.TemporaryDirectory() as directory:
            workbook_path = Path(directory) / "ims-memo-normalized.xlsx"
            pd.DataFrame(
                [
                    ["Bilim İlaç Brick Analizi", None, None, None, None],
                    ["Coğrafya", "Coğrafya", "Saha", "Ürün", "Metrik"],
                    ["Bölge", "İl", "Temsilci", "Ürün Grubu", "TL"],
                    ["Marmara", "İstanbul", "Ayşe Kaya", "Travazol", 300.5],
                    ["Marmara", "İstanbul", "Ayşe Kaya", "Travazol", 110.5],
                ]
            ).to_excel(workbook_path, index=False, header=False, sheet_name="TL")

            service = IMSImportService(workbook_path, uploaded_by="Test User")
            with mock.patch.object(AliasService, "find_product", wraps=AliasService.find_product) as find_product:
                result = service.run(2026, 5)

        self.assertTrue(result["success"], result["errors"])
        self.assertEqual(find_product.call_count, 1)
        self.assertEqual(IMSRawData.query.count(), 1)

    def test_shifted_header_and_noise_rows_are_tolerated(self):
        with tempfile.TemporaryDirectory() as directory:
            workbook_path = Path(directory) / "shifted_noise.xlsx"
            pd.DataFrame(
                [
                    ["Random note", None, None],
                    ["Another note", None, None],
                    ["Representative", "Travazol Box", "Travazol TL"],
                    ["Ayşe Kaya", 7, 140.0],
                    ["Toplam", 7, 140.0],
                    ["Note: internal", None, None],
                ]
            ).to_excel(workbook_path, index=False, header=False, sheet_name="BRICK SATIS")
            result = IMSImportService(workbook_path, uploaded_by="Test User").run(2026, 6)

        self.assertTrue(result["success"], result["errors"])
        self.assertEqual(IMSRawData.query.count(), 1)

    def test_merged_cells_and_partial_sheet_do_not_abort_import(self):
        with tempfile.TemporaryDirectory() as directory:
            workbook_path = Path(directory) / "merged_partial.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "BRICK SATIS"
            sheet["A1"] = "IMS Performans Raporu"
            sheet.merge_cells("A1:C1")
            sheet["A2"] = "Representative"
            sheet["B2"] = "Travazol Box"
            sheet["C2"] = "Travazol TL"
            sheet["A3"] = "Ayşe Kaya"
            sheet["B3"] = 3
            sheet["C3"] = 75
            partial = workbook.create_sheet("Partial")
            partial["A1"] = "Only title"
            workbook.save(workbook_path)
            result = IMSImportService(workbook_path, uploaded_by="Test User").run(2026, 6)

        self.assertTrue(result["success"], result["errors"])
        self.assertEqual(IMSRawData.query.count(), 1)

    def test_mixed_language_headers_normalized_sheet(self):
        with tempfile.TemporaryDirectory() as directory:
            workbook_path = Path(directory) / "mixed_language.xlsx"
            pd.DataFrame(
                [
                    ["Bilim İlaç Brick Analizi", None, None, None, None],
                    ["Region", "İl", "Temsilci", "Ürün Grubu", "Kutu"],
                    ["Marmara", "İstanbul", "Ayşe Kaya", "Travazol", 9],
                ]
            ).to_excel(workbook_path, index=False, header=False, sheet_name="BOX")
            result = IMSImportService(workbook_path, uploaded_by="Test User").run(2026, 7)

        self.assertTrue(result["success"], result["errors"])
        self.assertEqual(IMSRawData.query.count(), 1)

    def test_corrupted_numeric_is_skipped_as_row_error_not_global_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            workbook_path = Path(directory) / "corrupted_numeric.xlsx"
            pd.DataFrame(
                [
                    ["IMS Performans Raporu", None, None],
                    ["Representative", "Travazol Box", "Travazol TL"],
                    ["Ayşe Kaya", "ABC", 100.0],
                    ["Ayşe Kaya", 5, 150.0],
                ]
            ).to_excel(workbook_path, index=False, header=False, sheet_name="BRICK SATIS")
            result = IMSImportService(workbook_path, uploaded_by="Test User").run(2026, 7)

        self.assertTrue(result["success"], result["errors"])
        reasons = {item["reason"] for item in result["skipped_logs"]}
        self.assertIn("invalid_numeric_value", reasons)
        self.assertEqual(IMSRawData.query.count(), 1)

    def test_region_and_province_unmatched_items_have_review_fields(self):
        db.session.query(Representative).delete()
        db.session.add(Representative(rep_code="R-100", rep_name="Ali Veli", region="Ege", city="İzmir", active=True))
        db.session.commit()
        AliasService.refresh()

        with tempfile.TemporaryDirectory() as directory:
            workbook_path = Path(directory) / "region_province_unmatched.xlsx"
            pd.DataFrame(
                [
                    ["Bilim İlaç Brick Analizi", None, None, None, None],
                    ["Coğrafya", "Coğrafya", "Saha", "Ürün", "Metrik"],
                    ["Bölge", "İl", "Temsilci", "Ürün Grubu", "TL"],
                    ["Bilinmeyen Bölge", "Bilinmeyen İl", "Ali Veli", "Travazol", 55.0],
                ]
            ).to_excel(workbook_path, index=False, header=False, sheet_name="TL")
            result = IMSImportService(workbook_path, uploaded_by="Test User").run(2026, 8)

        self.assertTrue(result["success"], result["errors"])
        queue_items = ManualMatchQueue.query.filter(
            ManualMatchQueue.entity_type.in_(
                [ManualMatchQueue.ENTITY_REGION, ManualMatchQueue.ENTITY_PROVINCE]
            )
        ).all()
        self.assertEqual(len(queue_items), 2)
        for item in queue_items:
            self.assertIsNotNone(item.source_value)
            self.assertIsNotNone(item.normalized_value)
            self.assertIsNotNone(item.import_id)
            self.assertIsNotNone(item.worksheet)
            self.assertIsNotNone(item.row_number)
            self.assertIsNotNone(item.reason)

    def test_fuzzy_matching_stays_deterministic(self):
        product = Product.query.first()
        AliasService.create_product_alias(product, "Travazol Plus")
        AliasService.refresh()
        first = AliasService.find_product("Travazol Pluz")
        second = AliasService.find_product("Travazol Pluz")
        self.assertTrue(first["matched"])
        self.assertEqual(first["object"].id, second["object"].id)
        self.assertEqual(first["method"], second["method"])


if __name__ == "__main__":
    unittest.main()
