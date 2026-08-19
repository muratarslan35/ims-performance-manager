"""Whole-workbook manifest and mandatory parser-coverage gate for IMS imports.

This layer runs before any active IMS rows are published. Every non-empty sheet
must be explicitly classified and assigned to either the generic representative
parser or a known specialised/master verifier. Unknown sheets are blocking.
"""
from __future__ import annotations

import re
from app.services.alias_service import AliasService


class WorkbookPreflight:
    """Classify every sheet and reject silent parser gaps."""

    # Order matters: more specific reports precede generic month/TL/KUTU names.
    RULES = (
        ("official_brick_spread", ("SATIS BRICK YAYILIM", "SATIŞ BRICK YAYILIM")),
        ("brick_sales", ("1001 BRICK SATIS", "BRICK SATIS", "BRICK SATIŞ")),
        ("brick_realization", ("BRICK REA",)),
        ("weekly_sales", ("TTS HAFTALIK CIKIS", "TTS HAFTALIK ÇIKIŞ")),
        ("balance", ("BAKIYE", "BAKİYE")),
        ("competition_pp", ("TTS REKABET PP", "REKABET PP")),
        ("competition_tl", ("AYLIK REKABET TL", "REKABET TL", "TTS REKABET TL")),
        ("competition_box", ("AYLIK REKABET KUTU", "REKABET KUTU", "TTS REKABET KUTU")),
        ("competition", ("TTS REKABET",)),
        ("representative_sales", ("TTS CIKIS", "TTS ÇIKIŞ")),
        ("official_national_region_aggregate", ("NATIONAL", "BOLGE TOPLAM", "BÖLGE TOPLAM", "GENEL TOPLAM")),
        ("master_pivot_derived", ("PIVOT", "MASTER", "PAZAR")),
    )

    MONTHS = {
        "OCAK", "SUBAT", "ŞUBAT", "MART", "NISAN", "NİSAN", "MAYIS", "HAZIRAN", "HAZİRAN",
        "TEMMUZ", "AGUSTOS", "AĞUSTOS", "EYLUL", "EYLÜL", "EKIM", "EKİM", "KASIM", "ARALIK",
    }

    SPECIALIZED = {
        "official_brick_spread", "brick_realization", "weekly_sales", "balance",
        "competition", "competition_tl", "competition_box", "competition_pp",
        "official_national_region_aggregate", "master_pivot_derived",
    }

    def __init__(self, service):
        self.service = service

    @staticmethod
    def _normalized(value):
        return AliasService.normalize(value)

    def _meaningful_cells(self, frame):
        count = 0
        for value in frame.to_numpy().ravel():
            if self.service.clean_text(value):
                count += 1
        return count

    def _header_signature(self, frame):
        rows = min(12, len(frame))
        cols = min(80, frame.shape[1]) if frame.shape[1] else 0
        values = []
        for row in range(rows):
            for col in range(cols):
                text = self.service.clean_text(frame.iloc[row, col])
                if text:
                    values.append(self._normalized(text))
        return " | ".join(values)

    def classify(self, sheet_name, frame):
        name = self._normalized(sheet_name)
        signature = self._header_signature(frame)
        combined = f"{name} | {signature}"

        for sheet_type, tokens in self.RULES:
            if any(self._normalized(token) in combined for token in tokens):
                return sheet_type

        # Month-only verification sheets and their explicit metric variants.
        words = set(re.findall(r"[A-ZÇĞİÖŞÜ]+", name))
        if words & {self._normalized(month) for month in self.MONTHS}:
            if "KUTU" in words:
                return "monthly_master_box"
            if "TL" in words:
                return "monthly_master_tl"
            return "monthly_master"

        # Generic KUTU/TL sheets are explicit master verification sources.
        if name in {"KUTU", "TL"}:
            return "master_pivot_derived"

        # A structurally valid representative sheet can use the generic parser
        # even when its title changes. This is deterministic header self-heal.
        header_row = self.service.find_header_row(frame)
        if header_row is not None:
            return "representative_sales"
        return "unknown"

    def build(self):
        manifest = []
        for sheet_name, frame in (self.service.workbook or {}).items():
            meaningful = self._meaningful_cells(frame)
            sheet_type = self.classify(sheet_name, frame) if meaningful else "explicit_nondata"
            header_row = self.service.find_header_row(frame) if meaningful else None
            coverage = "explicit_nondata" if not meaningful else (
                "generic_parser" if header_row is not None else (
                    "specialized_parser" if sheet_type in self.SPECIALIZED or sheet_type.startswith("monthly_master") else "unclassified"
                )
            )
            manifest.append({
                "sheet_name": str(sheet_name),
                "rows": int(frame.shape[0]),
                "columns": int(frame.shape[1]),
                "meaningful_cells": meaningful,
                "header_row": header_row,
                "sheet_type": sheet_type,
                "coverage": coverage,
            })
        return manifest

    def validate(self):
        manifest = self.build()
        unclassified = [item for item in manifest if item["coverage"] == "unclassified" or item["sheet_type"] == "unknown"]
        self.service.workbook_manifest = manifest
        self.service.statistics["manifest_sheet_count"] = len(manifest)
        self.service.statistics["manifest_verified_sheets"] = len(manifest) - len(unclassified)
        self.service.statistics["unclassified_sheet"] = len(unclassified)
        self.service.statistics.setdefault("unclassified_master_cell", 0)
        self.service.statistics.setdefault("conflicting_match", 0)
        self.service.statistics.setdefault("duplicate_conflict", 0)
        self.service.statistics.setdefault("auto_repaired", 0)
        self.service.parser_decisions.extend(
            {"sheet_name": item["sheet_name"], "sheet_type": item["sheet_type"], "coverage": item["coverage"]}
            for item in manifest
        )
        if unclassified:
            names = ", ".join(item["sheet_name"] for item in unclassified)
            raise ValueError(f"Workbook preflight başarısız; sınıflandırılmamış sheet: {names}")
        return manifest


def install_workbook_preflight() -> None:
    """Install preflight without changing existing dashboard/import semantics."""
    from app.services.ims_import_service import IMSImportService

    if getattr(IMSImportService, "_whole_workbook_preflight_installed", False):
        return

    original_process = IMSImportService.process_workbook
    original_report = IMSImportService.report

    def process_with_preflight(self, year, month, week_number=None):
        WorkbookPreflight(self).validate()
        return original_process(self, year, month, week_number=week_number)

    def report_with_manifest(self):
        report = original_report(self)
        report["workbook_manifest"] = getattr(self, "workbook_manifest", [])
        report["final_result"] = "PASS" if (
            not report.get("errors")
            and self.statistics.get("unclassified_sheet", 0) == 0
            and self.statistics.get("unclassified_master_cell", 0) == 0
        ) else "FAIL"
        return report

    IMSImportService.process_workbook = process_with_preflight
    IMSImportService.report = report_with_manifest
    IMSImportService._whole_workbook_preflight_installed = True
