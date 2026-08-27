"""Semantic discovery adapters for import capabilities whose legacy entrypoints used sheet names.

Sheet names remain a backwards-compatible hint only. Future workbooks may rename
or reorder sheets; content structure decides whether a target or competition
capability is present. Ambiguous content is never guessed.
"""
from __future__ import annotations

import re

from app.services.alias_service import AliasService


def _norm(value):
    return AliasService.normalize(value)


def _frame_text(frame, rows=30):
    values = []
    for row in range(min(rows, len(frame))):
        for value in frame.iloc[row].tolist():
            normalized = _norm(value)
            if normalized:
                values.append(normalized)
    return values, " | ".join(values)


def _competition_signature_from_frame(frame):
    """Return preflight competition type or None using strong content evidence."""
    values, text = _frame_text(frame)
    if not values:
        return None
    has_rep = any(token in text for token in (
        "TTS ISMI", "TEMSILCI", "REPRESENTATIVE", "1 TTS ISMI", "2 TTS ISMI",
    ))
    has_geo = any(token in text for token in (
        "IAM BRICK", "BRICK", "TERRITOR", "BOLGE", "REGION",
    ))
    if not has_geo:
        return None
    if "HEDEF" in text or "TARGET" in text or "REALIZASYON" in text or "REALİZASYON" in text:
        return None

    generic = {
        "TTS", "ISMI", "TEMSILCI", "REPRESENTATIVE", "IAM", "BRICK", "TERRITORIES",
        "TERRITORY", "SUBTERRITORIES", "SUBTERRITORY", "BOLGE", "REGION", "TL",
        "KUTU", "UNIT", "UNITS", "VALUES", "VALUE", "REPORT", "PP", "PAZAR", "PAYI",
        "MARKET", "SHARE", "TOPLAM", "TOTAL", "GRAND", "CIKIS", "ÇIKIŞ", "AYLIK",
        "HAFTALIK", "MONTH", "WEEK",
    }
    productish = set()
    for value in values:
        tokens = set(re.findall(r"[A-Z0-9ÇĞİÖŞÜ]+", value))
        if not tokens or tokens <= generic:
            continue
        if len(value) < 3 or any(marker in value for marker in ("PIVOTTABLE", "GROUPTABLE")):
            continue
        productish.add(value)
    explicit_competition = any(token in text for token in ("REKABET", "RAKIP", "RAKİP", "COMPETITOR"))
    if not explicit_competition and len(productish) < 18:
        return None

    has_share = any(token in text for token in ("PAZAR PAY", "MARKET SHARE", "VALUE SHARE", " PP ", "| PP"))
    has_unit = any(token in text for token in ("KUTU", "UNITS REPORT", "UNIT REPORT", " BOX ", "ADET"))
    has_value = any(token in text for token in ("VALUES REPORT", "VALUE REPORT", " CIRO ", " TUTAR ", " TL ", "| TL"))
    if has_share:
        return "competition_pp"
    if has_value and not has_unit:
        return "competition_tl"
    if has_unit and not has_value:
        return "competition_box"
    return None


def _worksheet_text(service, sheet_name, rows=30):
    sheet = service._workbook[sheet_name]
    values = []
    for row in sheet.iter_rows(min_row=1, max_row=min(rows, sheet.max_row or 0), values_only=True):
        for value in row:
            normalized = _norm(value)
            if normalized:
                values.append(normalized)
    return values, " | ".join(values)


def _competition_type_for_loaded_sheet(service, sheet_name):
    from app.services.competition_import_service import SheetType

    cache = getattr(service, "_semantic_sheet_type_cache", None)
    if cache is None:
        cache = {}
        service._semantic_sheet_type_cache = cache
    if sheet_name in cache:
        return cache[sheet_name]

    named = service.classify_sheet(sheet_name)
    values, text = _worksheet_text(service, sheet_name)
    if not values:
        cache[sheet_name] = None
        return None
    has_rep = any(token in text for token in ("TTS ISMI", "TEMSILCI", "REPRESENTATIVE", "1 TTS ISMI", "2 TTS ISMI"))
    has_geo = any(token in text for token in ("IAM BRICK", "BRICK", "TERRITOR", "BOLGE", "REGION"))
    if not has_geo or any(token in text for token in ("HEDEF", "TARGET", "REALIZASYON", "REALİZASYON")):
        cache[sheet_name] = named
        return named
    explicit = any(token in text for token in ("REKABET", "RAKIP", "RAKİP", "COMPETITOR"))
    generic = {
        "TTS", "ISMI", "TEMSILCI", "REPRESENTATIVE", "IAM", "BRICK", "TERRITORIES",
        "TERRITORY", "SUBTERRITORIES", "SUBTERRITORY", "BOLGE", "REGION", "TL",
        "KUTU", "UNIT", "UNITS", "VALUES", "VALUE", "REPORT", "PP", "PAZAR", "PAYI",
        "MARKET", "SHARE", "TOPLAM", "TOTAL", "GRAND", "CIKIS", "ÇIKIŞ", "AYLIK",
        "HAFTALIK", "MONTH", "WEEK", "NATIONAL",
    }
    productish = set()
    for value in values:
        tokens = set(re.findall(r"[A-Z0-9ÇĞİÖŞÜ]+", value))
        if not tokens or tokens <= generic:
            continue
        if len(value) < 3 or any(marker in value for marker in ("PIVOTTABLE", "GROUPTABLE")):
            continue
        productish.add(value)
    if not explicit and len(productish) < 18:
        cache[sheet_name] = named
        return named
    if not has_rep and len(productish) < 18:
        cache[sheet_name] = named
        return named
    exact_values = set(values)
    has_monthly_scope = bool(exact_values & {"AYLIK", "MONTHLY", "MONTHLY REPORT", "AYLIK RAPOR"})
    has_weekly_scope = bool(exact_values & {"HAFTALIK", "WEEKLY", "WEEKLY REPORT", "HAFTALIK RAPOR"})
    monthly_matrix = has_monthly_scope or (
        "IAM BRICK" in text and any(token in text for token in ("1 TTS ISMI", "2 TTS ISMI"))
    )
    has_share = any(token in text for token in ("PAZAR PAY", "MARKET SHARE", "VALUE SHARE", " PP ", "| PP"))
    has_unit = any(token in text for token in ("KUTU", "UNITS REPORT", "UNIT REPORT", " BOX ", "ADET"))
    has_value = any(token in text for token in ("VALUES REPORT", "VALUE REPORT", " CIRO ", " TUTAR ", " TL ", "| TL"))
    if has_share:
        result = SheetType.MARKET_REFERENCE
    elif has_weekly_scope and not monthly_matrix:
        result = SheetType.WEEKLY_VALUE if has_value and not has_unit else SheetType.WEEKLY_UNITS
    elif has_value and not has_unit:
        result = SheetType.MONTHLY_COMPETITION_VALUE
    elif has_unit and not has_value:
        result = SheetType.MONTHLY_COMPETITION_UNITS
    elif monthly_matrix:
        result = SheetType.MONTHLY_COMPETITION_UNITS
    else:
        result = named
    cache[sheet_name] = result
    return result


def install_semantic_import_discovery():
    from app.services.workbook_preflight import WorkbookPreflight
    from app.services.target_import_service import TargetImportService
    from app.services.competition_import_service import CompetitionImportService
    from app.services.ims_import_service import IMSImportService

    if getattr(IMSImportService, "_semantic_import_discovery_installed", False):
        return

    original_preflight_classify = WorkbookPreflight._content_classify

    def content_classify_with_competition(self, frame):
        detected = original_preflight_classify(self, frame)
        competition = _competition_signature_from_frame(frame)
        if competition and detected in {None, "representative_sales"}:
            return competition
        return detected

    WorkbookPreflight._content_classify = content_classify_with_competition

    original_target_check = TargetImportService._is_target_sheet

    def target_sheet_by_content(self, sheet_name, dataframe):
        if original_target_check(self, sheet_name, dataframe):
            return True
        _values, text = _frame_text(dataframe, rows=20)
        if "HEDEF" not in text and "TARGET" not in text:
            return False
        if any(token in text for token in ("CIKIS", "ÇIKIŞ", "REALIZASYON", "REALİZASYON")):
            return False
        has_rep = any(token in text for token in self.REPRESENTATIVE_HEADERS)
        has_metric = any(token in text for token in ("TL", "CIRO", "TUTAR", "VALUE", "KUTU", "BOX", "ADET", "UNIT"))
        product_matches = 0
        seen = set()
        for value in _values:
            if value in seen:
                continue
            seen.add(value)
            match = AliasService.find_product(value)
            if match.get("matched") and match.get("method") in self.STRICT_PRODUCT_MATCH_METHODS:
                product_matches += 1
        return has_rep and has_metric and product_matches >= 2

    TargetImportService._is_target_sheet = target_sheet_by_content

    original_supported = CompetitionImportService.get_supported_sheets
    original_get_type = CompetitionImportService.get_sheet_type

    def supported_by_content(self):
        if not self._workbook:
            return []
        named = original_supported(self)
        supported = list(named)
        for sheet_name in self._workbook.sheetnames:
            if sheet_name in supported:
                # Populate the cache for legacy names as well so get_sheet_type
                # never has to rescan the header surface later.
                _competition_type_for_loaded_sheet(self, sheet_name)
                continue
            if _competition_type_for_loaded_sheet(self, sheet_name) is not None:
                supported.append(sheet_name)
        return supported

    def type_by_content(self, sheet_name):
        from app.services.competition_import_service import SheetType
        named = self.classify_sheet(sheet_name)
        semantic = _competition_type_for_loaded_sheet(self, sheet_name)
        if named is None:
            if semantic is None:
                return original_get_type(self, sheet_name)
            return semantic.value
        if named == SheetType.WEEKLY_UNITS and semantic in {
            SheetType.MONTHLY_COMPETITION_UNITS,
            SheetType.MONTHLY_COMPETITION_VALUE,
            SheetType.MARKET_REFERENCE,
        }:
            return semantic.value
        return named.value

    CompetitionImportService.get_supported_sheets = supported_by_content
    CompetitionImportService.get_sheet_type = type_by_content

    original_process = IMSImportService.process_workbook

    def process_with_competition_fallback(self, year, month, week_number=None):
        result = original_process(self, year, month, week_number=week_number)
        if CompetitionImportService.has_competition_sheets((self.workbook or {}).keys()):
            return result

        # Reuse the sanitized dataframes already loaded by IMSImportService.
        # The previous fallback opened the same Excel file twice more (probe +
        # real import), which dominated production time after semantic support
        # was introduced. Discovery and persistence now share one prepared view.
        competition = CompetitionImportService(
            file_path=self.file_path,
            upload_id=self.upload.id,
            year=year,
            month=month,
            week_number=week_number,
            workbook=self.workbook,
        )
        supported = competition.get_supported_sheets()
        if not supported:
            return result
        competition_result = competition.run()
        summary = competition_result.get("summary", {})
        self.statistics["competition_records"] = summary.get("total_inserted", 0)
        self.statistics["competition_duplicates"] = summary.get("total_duplicates", 0)
        self.statistics["competition_invalid"] = summary.get("total_invalid", 0)
        self.statistics["competition_source_records"] = summary.get("numeric_cells", 0)
        self.statistics["competition_semantic_discovery"] = 1
        self.statistics["competition_reused_prepared_workbook"] = 1
        self.warnings = [
            warning for warning in self.warnings
            if "Rekabet etiketi taşıyan bir sayfa bulunmadığı için rekabet importu atlandı" not in str(warning)
        ]
        self._finalize_source_reconciliation()
        return result

    IMSImportService.process_workbook = process_with_competition_fallback
    IMSImportService._semantic_import_discovery_installed = True
