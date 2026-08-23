"""Atomic import for approved 1./2. production realization workbooks."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from app.extensions import db
from app.models import (
    Product,
    ProductAlias,
    ProductionRepresentativeTotal,
    ProductionNationalProductResult,
    ProductionNationalTotal,
    ProductionRegionProductResult,
    ProductionRegionTotal,
    ProductionResult,
    Representative,
    RepresentativeAlias,
    Target,
)
from app.services.alias_service import AliasService


class ProductionWorkbookValidationError(ValueError):
    """Validation failure that must leave all production overrides unapplied."""


@dataclass
class ProductionImportReport:
    rows_seen: int = 0
    matched_rows: int = 0
    product_results: list = field(default_factory=list)
    representative_totals: list = field(default_factory=list)
    region_totals: list = field(default_factory=list)
    region_product_results: list = field(default_factory=list)
    national_product_results: list = field(default_factory=list)
    national_total: dict | None = None
    target_mismatch_count: int = 0

    @property
    def matched_result_count(self):
        return len(self.product_results)


class ProductionResultImportService:
    """Read KOTA SATIŞ production files while retaining exact TL and unit data."""

    PRODUCT_COUNT = 7
    PERCENT_TOLERANCE = 0.05

    def __init__(self, file_path, year, month):
        self.file_path = Path(file_path)
        self.year = int(year)
        self.month = int(month)
        self._products = {}
        self._representatives = {}
        self._vacancies = {}

    @staticmethod
    def _number(value):
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        value = str(value).strip().replace("%", "").replace("\u00a0", "")
        if not value or value in {"-", "—"}:
            return None
        if "," in value:
            value = value.replace(".", "").replace(",", ".")
        try:
            return float(value)
        except ValueError:
            return None

    @staticmethod
    def _is_region(label):
        return len(label) > 4 and label[:3].isdigit() and label[3] == " "

    def _load_master_maps(self):
        normalize = AliasService.normalize
        for product in Product.query.all():
            for label in (product.product_name, product.product_code, product.ims_name):
                if label:
                    self._products[normalize(label)] = product
        for alias in ProductAlias.query.all():
            self._products[normalize(alias.alias_name)] = alias.product

        for representative in Representative.query.filter_by(active=True).all():
            for label in (representative.rep_name, representative.rep_code, representative.ims_code):
                if label:
                    self._representatives[normalize(label)] = representative
            if str(representative.rep_code or "").upper().startswith("UNASSIGNED"):
                region_key = normalize(representative.region).split(" ", 1)[0]
                self._vacancies.setdefault(region_key, []).append(representative)
        for alias in RepresentativeAlias.query.all():
            if alias.representative and alias.representative.active:
                self._representatives[normalize(alias.alias_name)] = alias.representative

    def _find_sheet(self, workbook, metric):
        metric = AliasService.normalize(metric)
        for sheet_name in workbook.sheetnames:
            normalized = AliasService.normalize(sheet_name)
            if "TTS REALIZASYONLARI" in normalized and metric in normalized:
                return workbook[sheet_name]
        raise ProductionWorkbookValidationError(f"TTS realizasyon {metric} sayfası bulunamadı.")

    def _layout(self, sheet, metric):
        metric = AliasService.normalize(metric)
        target_label, actual_label = f"{metric} HEDEF", f"{metric} CIKIS"
        for row_number in range(1, min(sheet.max_row, 12) + 1):
            values = [AliasService.normalize(sheet.cell(row_number, column).value) for column in range(1, sheet.max_column + 1)]
            try:
                target_total = values.index(target_label) + 1
                actual_total = values.index(actual_label) + 1
            except ValueError:
                continue
            percent_total = next((i + 1 for i, value in enumerate(values) if value in {"REA", "REALIZASYON"}), None)
            # The TL sheet carries the selected production total (``1. URETIM``
            # or ``2. URETIM``). The unit sheet ends at REA% in some approved
            # workbooks, so its final total is the REA% total.
            stage_two = next((i + 1 for i, value in enumerate(values) if value == "2 URETIM"), None)
            stage_one = next((i + 1 for i, value in enumerate(values) if value == "1 URETIM"), None)
            if percent_total is None:
                continue
            starts = (target_total - self.PRODUCT_COUNT, actual_total - self.PRODUCT_COUNT, percent_total - self.PRODUCT_COUNT)
            if min(starts) < 1:
                continue
            product_ids = []
            for column in range(starts[0], target_total):
                product = self._products.get(values[column - 1])
                if product is None:
                    break
                product_ids.append(product.id)
            if len(product_ids) == self.PRODUCT_COUNT and len(set(product_ids)) == self.PRODUCT_COUNT:
                return {
                    "header_row": row_number,
                    "name_column": starts[0] - 1,
                    "region_column": starts[0] - 2,
                    "actual_columns": list(range(starts[1], actual_total)),
                    "target_columns": list(range(starts[0], target_total)),
                    "percent_columns": list(range(starts[2], percent_total)),
                    "product_ids": product_ids,
                    "total_actual_column": actual_total,
                    "total_percent_column": (
                        stage_two if metric == "TL" and stage_two is not None
                        else stage_one if metric == "TL" and stage_one is not None
                        else percent_total
                    ),
                }
        raise ProductionWorkbookValidationError(f"{sheet.title} başlıkları KOTA SATIŞ şemasıyla eşleşmiyor.")

    def _match_representative(self, raw_name, raw_region):
        name, region = AliasService.normalize(raw_name), AliasService.normalize(raw_region)
        if not name or name == "NATIONAL" or self._is_region(name):
            return None
        representative = self._representatives.get(name)
        if representative is not None:
            return representative
        region_key = region.split(" ", 1)[0]
        candidates = [item for item in self._vacancies.get(region_key, []) if AliasService.normalize(item.rep_name).endswith(name)]
        return candidates[0] if len(candidates) == 1 else None

    def _read_sheet(self, sheet, metric):
        layout = self._layout(sheet, metric)
        rows, unresolved, duplicates = {}, [], []
        for row_number in range(layout["header_row"] + 1, sheet.max_row + 1):
            raw_name = sheet.cell(row_number, layout["name_column"]).value
            raw_region = sheet.cell(row_number, layout["region_column"]).value
            label = AliasService.normalize(raw_name)
            if not label or label == "NATIONAL" or self._is_region(label):
                continue
            representative = self._match_representative(raw_name, raw_region)
            if representative is None:
                unresolved.append(str(raw_name).strip())
                continue
            if representative.id in rows:
                duplicates.append(representative.rep_name)
                continue
            targets, values, percentages = [], [], []
            for target_column, actual_column, percent_column in zip(layout["target_columns"], layout["actual_columns"], layout["percent_columns"]):
                target = self._number(sheet.cell(row_number, target_column).value)
                value = self._number(sheet.cell(row_number, actual_column).value)
                percent = self._number(sheet.cell(row_number, percent_column).value)
                if target is None or value is None or percent is None or target < 0 or value < 0 or percent < 0:
                    raise ProductionWorkbookValidationError(f"{sheet.title}!{row_number} satırında geçersiz sonuç değeri var.")
                targets.append(target)
                values.append(value)
                percentages.append(percent)
            total_target = self._number(sheet.cell(row_number, layout["target_columns"][-1] + 1).value)
            total_actual = self._number(sheet.cell(row_number, layout["total_actual_column"]).value)
            total_percent = self._number(sheet.cell(row_number, layout["total_percent_column"]).value)
            if total_target is None or total_actual is None or total_percent is None:
                raise ProductionWorkbookValidationError(f"{sheet.title}!{row_number} satırında nihai toplam eksik.")
            rows[representative.id] = {
                "row_number": row_number, "targets": targets, "values": values, "percentages": percentages,
                "total_target": total_target, "total_actual": total_actual, "total_percent": total_percent,
                "product_ids": layout["product_ids"],
            }
        if unresolved:
            raise ProductionWorkbookValidationError("Eşleşmeyen temsilci/boş kadro satırları: " + ", ".join(sorted(set(unresolved))[:10]))
        if duplicates:
            raise ProductionWorkbookValidationError("Bir temsilci birden fazla kez bulundu: " + ", ".join(sorted(set(duplicates))[:10]))
        return rows

    def _read_national(self, sheet, metric):
        """Read the workbook's NATIONAL row; never infer it from rep rows."""
        layout = self._layout(sheet, metric)
        for row_number in range(layout["header_row"] + 1, sheet.max_row + 1):
            if AliasService.normalize(sheet.cell(row_number, layout["name_column"]).value) != "NATIONAL":
                continue
            targets, values, percentages = [], [], []
            for target_column, actual_column, percent_column in zip(layout["target_columns"], layout["actual_columns"], layout["percent_columns"]):
                target = self._number(sheet.cell(row_number, target_column).value)
                actual = self._number(sheet.cell(row_number, actual_column).value)
                percent = self._number(sheet.cell(row_number, percent_column).value)
                if target is None or actual is None or percent is None:
                    raise ProductionWorkbookValidationError(f"{sheet.title}!{row_number} NATIONAL değeri eksik.")
                targets.append(target); values.append(actual); percentages.append(percent)
            total_target = self._number(sheet.cell(row_number, layout["target_columns"][-1] + 1).value)
            total_actual = self._number(sheet.cell(row_number, layout["total_actual_column"]).value)
            total_percent = self._number(sheet.cell(row_number, layout["total_percent_column"]).value)
            if total_target is None or total_actual is None or total_percent is None:
                raise ProductionWorkbookValidationError(f"{sheet.title}!{row_number} NATIONAL toplamı eksik.")
            return {"row_number": row_number, "targets": targets, "values": values, "percentages": percentages, "total_target": total_target, "total_actual": total_actual, "total_percent": total_percent, "product_ids": layout["product_ids"]}
        raise ProductionWorkbookValidationError(f"{sheet.title} NATIONAL satırı bulunamadı.")

    def _read_regions(self, sheet, metric):
        """Read workbook-owned region subtotal rows; never infer them from reps."""
        layout = self._layout(sheet, metric)
        rows = {}
        for row_number in range(layout["header_row"] + 1, sheet.max_row + 1):
            label = AliasService.normalize(sheet.cell(row_number, layout["name_column"]).value)
            if not self._is_region(label):
                continue
            targets, values, percentages = [], [], []
            for target_column, actual_column, percent_column in zip(layout["target_columns"], layout["actual_columns"], layout["percent_columns"]):
                target = self._number(sheet.cell(row_number, target_column).value)
                actual = self._number(sheet.cell(row_number, actual_column).value)
                percent = self._number(sheet.cell(row_number, percent_column).value)
                if target is None or actual is None or percent is None:
                    raise ProductionWorkbookValidationError(f"{sheet.title}!{row_number} bölge toplamı eksik.")
                targets.append(target); values.append(actual); percentages.append(percent)
            total_target = self._number(sheet.cell(row_number, layout["target_columns"][-1] + 1).value)
            total_actual = self._number(sheet.cell(row_number, layout["total_actual_column"]).value)
            total_percent = self._number(sheet.cell(row_number, layout["total_percent_column"]).value)
            if total_target is None or total_actual is None or total_percent is None:
                raise ProductionWorkbookValidationError(f"{sheet.title}!{row_number} bölge nihai toplamı eksik.")
            rows[label.split(" ", 1)[0]] = {
                "row_number": row_number, "targets": targets, "values": values,
                "percentages": percentages, "total_target": total_target,
                "total_actual": total_actual, "total_percent": total_percent,
                "product_ids": layout["product_ids"],
            }
        return rows

    def parse(self):
        if not self.file_path.exists():
            raise ProductionWorkbookValidationError("Üretim Excel dosyası bulunamadı.")
        try:
            workbook = load_workbook(self.file_path, read_only=False, data_only=True)
        except Exception as exc:
            raise ProductionWorkbookValidationError("Excel dosyası okunamadı.") from exc
        self._load_master_maps()
        tl_sheet, unit_sheet = self._find_sheet(workbook, "TL"), self._find_sheet(workbook, "KUTU")
        tl_rows, unit_rows = self._read_sheet(tl_sheet, "TL"), self._read_sheet(unit_sheet, "KUTU")
        region_tl, region_unit = self._read_regions(tl_sheet, "TL"), self._read_regions(unit_sheet, "KUTU")
        national_tl, national_unit = self._read_national(tl_sheet, "TL"), self._read_national(unit_sheet, "KUTU")
        if set(tl_rows) != set(unit_rows):
            raise ProductionWorkbookValidationError("TL ve kutu sonuçlarında temsilci kapsamı eşit değil.")
        if set(region_tl) != set(region_unit):
            raise ProductionWorkbookValidationError("TL ve kutu sonuçlarında bölge kapsamı eşit değil.")
        targets = {(row.representative_id, row.product_id): row for row in Target.query.filter_by(year=self.year, month=self.month).all()}
        source_keys = {(rep_id, product_id) for rep_id, row in tl_rows.items() for product_id in row["product_ids"]}
        if source_keys != set(targets):
            raise ProductionWorkbookValidationError(f"Üretim dosyası kapsamı dönem hedefleriyle eşit değil (eksik={len(set(targets)-source_keys)}, fazlalık={len(source_keys-set(targets))}).")
        report = ProductionImportReport(rows_seen=len(tl_rows), matched_rows=len(tl_rows))
        for index, product_id in enumerate(national_tl["product_ids"]):
            report.national_product_results.append({"product_id": product_id, "actual_tl": national_tl["values"][index], "actual_unit": national_unit["values"][index], "realization_percent": national_tl["percentages"][index], "unit_realization_percent": national_unit["percentages"][index], "source_sheet": tl_sheet.title, "source_row": national_tl["row_number"]})
        report.national_total = {"target_tl": national_tl["total_target"], "target_unit": national_unit["total_target"], "actual_tl": national_tl["total_actual"], "actual_unit": national_unit["total_actual"], "realization_percent": national_tl["total_percent"], "unit_realization_percent": national_unit["total_percent"], "source_sheet": tl_sheet.title, "source_row": national_tl["row_number"]}
        for region_code, tl_row in region_tl.items():
            unit_row = region_unit[region_code]
            report.region_totals.append({"region_code": region_code, "target_tl": tl_row["total_target"], "target_unit": unit_row["total_target"], "actual_tl": tl_row["total_actual"], "actual_unit": unit_row["total_actual"], "realization_percent": tl_row["total_percent"], "unit_realization_percent": unit_row["total_percent"], "source_sheet": tl_sheet.title, "source_row": tl_row["row_number"]})
            for index, product_id in enumerate(tl_row["product_ids"]):
                report.region_product_results.append({"region_code": region_code, "product_id": product_id, "target_tl": tl_row["targets"][index], "target_unit": unit_row["targets"][index], "actual_tl": tl_row["values"][index], "actual_unit": unit_row["values"][index], "realization_percent": tl_row["percentages"][index], "unit_realization_percent": unit_row["percentages"][index], "source_sheet": tl_sheet.title, "source_row": tl_row["row_number"]})
        for representative_id, tl_row in tl_rows.items():
            unit_row = unit_rows[representative_id]
            for index, product_id in enumerate(tl_row["product_ids"]):
                database_target = targets[(representative_id, product_id)]
                actual_tl, actual_unit, percent = tl_row["values"][index], unit_row["values"][index], tl_row["percentages"][index]
                source_target_tl, source_target_unit = tl_row["targets"][index], unit_row["targets"][index]
                expected = actual_tl * 100 / source_target_tl if source_target_tl else 0.0
                if abs(percent - expected) > self.PERCENT_TOLERANCE:
                    raise ProductionWorkbookValidationError(f"{tl_sheet.title}!{tl_row['row_number']} TL realizasyonu doğrulanamadı.")
                if abs(source_target_tl - float(database_target.tl_target or 0)) > self.PERCENT_TOLERANCE or abs(source_target_unit - float(database_target.unit_target or 0)) > self.PERCENT_TOLERANCE:
                    report.target_mismatch_count += 1
                unit_percent = unit_row["percentages"][index]
                if unit_percent is None:
                    raise ProductionWorkbookValidationError(f"{unit_sheet.title}!{unit_row['row_number']} kutu realizasyonu eksik.")
                expected_unit_percent = actual_unit * 100 / source_target_unit if source_target_unit else 0.0
                if abs(unit_percent - expected_unit_percent) > self.PERCENT_TOLERANCE:
                    raise ProductionWorkbookValidationError(f"{unit_sheet.title}!{unit_row['row_number']} kutu realizasyonu doğrulanamadı.")
                report.product_results.append({"representative_id": representative_id, "product_id": product_id, "realization_percent": percent, "unit_realization_percent": unit_percent, "target_tl": source_target_tl, "target_unit": source_target_unit, "actual_tl": actual_tl, "actual_unit": actual_unit, "source_sheet": tl_sheet.title, "source_row": tl_row["row_number"]})
            report.representative_totals.append({"representative_id": representative_id, "realization_percent": tl_row["total_percent"], "unit_realization_percent": unit_row["total_percent"], "target_tl": tl_row["total_target"], "target_unit": unit_row["total_target"], "actual_tl": tl_row["total_actual"], "actual_unit": unit_row["total_actual"], "source_sheet": tl_sheet.title, "source_row": tl_row["row_number"]})
        return report

    @staticmethod
    def apply(upload, report):
        for row in report.product_results:
            db.session.add(ProductionResult(upload_id=upload.id, **row))
        for row in report.representative_totals:
            db.session.add(ProductionRepresentativeTotal(upload_id=upload.id, **row))
        for row in report.national_product_results:
            db.session.add(ProductionNationalProductResult(upload_id=upload.id, **row))
        db.session.add(ProductionNationalTotal(upload_id=upload.id, **report.national_total))
        ProductionResultImportService.apply_region_totals(upload, report)
        upload.row_count, upload.matched_row_count = report.rows_seen, report.matched_result_count
        upload.status = upload.STATUS_APPLIED
        upload.validated_at = datetime.utcnow()
        upload.applied_at = datetime.utcnow()
        upload.warning_message = f"{report.matched_rows} temsilci ve {report.matched_result_count} ürün satırı doğrulandı. TL/kutu hedef ve sonuçları üretim dosyasındaki nihai değerleriyle ayrı korunur; öncelik 2. üretim → 1. üretim → IMS'tir." + (f" {report.target_mismatch_count} IMS hedef farkı, kaynak veriyi değiştirmeden üretim sonucu kapsamında kaydedildi." if report.target_mismatch_count else "")

    @staticmethod
    def apply_region_totals(upload, report):
        """Upsert official region rows; safe to call for historical backfill."""
        ProductionRegionProductResult.query.filter_by(upload_id=upload.id).delete(synchronize_session=False)
        ProductionRegionTotal.query.filter_by(upload_id=upload.id).delete(synchronize_session=False)
        for row in report.region_product_results:
            db.session.add(ProductionRegionProductResult(upload_id=upload.id, **row))
        for row in report.region_totals:
            db.session.add(ProductionRegionTotal(upload_id=upload.id, **row))
