"""Safe importer for final post-sales production realization workbooks.

Production files contain final realization percentages, not a replacement for
IMS targets or raw sales.  This importer therefore writes only the dedicated
production result tables; the existing resolution service applies P2 > P1 >
IMS at read time.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from app.extensions import db
from app.models import ProductionRepresentativeTotal, ProductionResult
from app.services.alias_service import AliasService


class ProductionWorkbookValidationError(ValueError):
    """Raised before any production result is persisted."""


@dataclass
class ProductionImportReport:
    rows_seen: int = 0
    matched_rows: int = 0
    product_results: list = field(default_factory=list)
    representative_totals: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def matched_result_count(self):
        return len(self.product_results)


class ProductionResultImportService:
    """Import a percentage-based production workbook without touching IMS."""

    MAX_PERCENT = 500
    HEADER_SCAN_ROWS = 80
    HEADER_SCAN_COLUMNS = 50
    TOTAL_HEADERS = {"TOPLAM", "REA", "REA %", "REAL", "REAL %", "REALIZASYON", "REALIZATION"}
    AGGREGATE_LABELS = {"NATIONAL", "TOPLAM", "TOTAL", "GENEL TOPLAM"}

    def __init__(self, file_path):
        self.file_path = Path(file_path)

    @staticmethod
    def _number(value):
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace("%", "").replace("\u00a0", "")
        if not text or text in {"-", "—"}:
            return None
        text = text.replace(".", "").replace(",", ".") if "," in text else text
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def _sheet_values(sheet):
        for row in sheet.iter_rows(values_only=True):
            yield list(row)

    def _find_product_headers(self, rows):
        """Return header row/column map where at least one master product exists."""
        for row_index, row in enumerate(rows[: self.HEADER_SCAN_ROWS]):
            product_columns = {}
            total_columns = []
            for column_index, value in enumerate(row[: self.HEADER_SCAN_COLUMNS]):
                label = AliasService.normalize(value)
                if not label:
                    continue
                match = AliasService.find_product(value, minimum_score=0.95)
                if match["matched"]:
                    product_columns[column_index] = match["object"]
                elif label in self.TOTAL_HEADERS:
                    total_columns.append(column_index)
            if product_columns:
                return row_index, product_columns, total_columns
        return None, {}, []

    def parse(self):
        if not self.file_path.exists():
            raise ProductionWorkbookValidationError("Üretim Excel dosyası bulunamadı.")
        try:
            workbook = load_workbook(self.file_path, read_only=True, data_only=True)
        except Exception as exc:
            raise ProductionWorkbookValidationError("Excel dosyası okunamadı.") from exc

        AliasService.refresh()
        report = ProductionImportReport()
        seen_keys = set()
        seen_totals = set()

        for sheet in workbook.worksheets:
            rows = list(self._sheet_values(sheet))
            header_index, product_columns, total_columns = self._find_product_headers(rows)
            if header_index is None:
                continue

            for excel_row, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
                if not row:
                    continue
                representative_label = row[0] if row else None
                normalized = AliasService.normalize(representative_label)
                if not normalized or normalized in self.AGGREGATE_LABELS:
                    continue
                representative_match = AliasService.find_representative(
                    representative_label, minimum_score=0.95
                )
                if not representative_match["matched"]:
                    # Region and vacancy rows are source context, never final individual results.
                    continue

                report.rows_seen += 1
                representative = representative_match["object"]
                row_matched = False
                for column_index, product in product_columns.items():
                    value = self._number(row[column_index] if column_index < len(row) else None)
                    if value is None:
                        continue
                    if value < 0 or value > self.MAX_PERCENT:
                        raise ProductionWorkbookValidationError(
                            f"{sheet.title}!{excel_row} satırındaki yüzde geçersiz: {value}."
                        )
                    key = (representative.id, product.id)
                    if key in seen_keys:
                        raise ProductionWorkbookValidationError(
                            f"{representative.rep_name} / {product.product_name} üretim sonucu birden fazla kez bulundu."
                        )
                    seen_keys.add(key)
                    report.product_results.append((representative.id, product.id, value, sheet.title, excel_row))
                    row_matched = True

                for column_index in total_columns:
                    value = self._number(row[column_index] if column_index < len(row) else None)
                    if value is None:
                        continue
                    if value < 0 or value > self.MAX_PERCENT:
                        raise ProductionWorkbookValidationError(
                            f"{sheet.title}!{excel_row} satırındaki toplam yüzde geçersiz: {value}."
                        )
                    if representative.id not in seen_totals:
                        seen_totals.add(representative.id)
                        report.representative_totals.append((representative.id, value, sheet.title, excel_row))
                if row_matched:
                    report.matched_rows += 1

        if not report.product_results:
            raise ProductionWorkbookValidationError(
                "Üretim dosyasında eşleşen temsilci/ürün realizasyon satırı bulunamadı. "
                "Başlıklar ürün, ilk sütun temsilci adı olmalıdır."
            )
        return report

    @staticmethod
    def apply(upload, report):
        """Persist one validated report. Caller owns the transaction."""
        for representative_id, product_id, percent, sheet_name, row_number in report.product_results:
            db.session.add(ProductionResult(
                upload_id=upload.id,
                representative_id=representative_id,
                product_id=product_id,
                realization_percent=percent,
                source_sheet=sheet_name,
                source_row=row_number,
            ))
        for representative_id, percent, sheet_name, row_number in report.representative_totals:
            db.session.add(ProductionRepresentativeTotal(
                upload_id=upload.id,
                representative_id=representative_id,
                realization_percent=percent,
                source_sheet=sheet_name,
                source_row=row_number,
            ))
        upload.row_count = report.rows_seen
        upload.matched_row_count = report.matched_result_count
        upload.status = upload.STATUS_APPLIED
        upload.validated_at = datetime.utcnow()
        upload.applied_at = datetime.utcnow()
        upload.warning_message = (
            f"{report.matched_rows} temsilci satırı ve {report.matched_result_count} ürün sonucu "
            "doğrulandı. Final öncelik 2. üretim → 1. üretim → IMS olarak uygulanır."
        )
