"""Content-first adapters that remove physical Excel-layout assumptions from IMS imports.

The contract is semantic: worksheet names, order, header row numbers and dimension
column positions are hints/audit metadata only.  A capability is selected from
its content.  When two worksheets are equally authoritative the importer fails
closed instead of guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional

from app.extensions import db
from app.models import IMSSummary, IMSRawData, Product, Representative, Target
from app.services.alias_service import AliasService
from app.services.target_box_calculation_service import TargetBoxCalculationService


_REGION_RE = re.compile(r"^\s*(\d{3})\b(?:\s+(.+))?$")
VALUE_TOKENS = (" TL ", "CIRO", "TUTAR", "VALUE", "VALUES REPORT", "VALUE REPORT")
UNIT_TOKENS = ("KUTU", "BOX", "ADET", "UNIT", "UNITS REPORT", "UNIT REPORT")
ACTUAL_TOKENS = ("CIKIS", "ÇIKIŞ", "ACTUAL", "SALES")
TARGET_TOKENS = ("HEDEF", "TARGET")
BALANCE_TOKENS = ("BAKIYE", "BALANCE")
WEEK_TOKENS = ("HAFTA", "WEEK")


def _norm(value) -> str:
    return AliasService.normalize(value)


def _has_any(text: str, tokens) -> bool:
    padded = f" {text} "
    return any(token in padded if token.startswith(" ") else token in text for token in tokens)


def _region_code(value) -> Optional[str]:
    match = _REGION_RE.match(_norm(value))
    return match.group(1) if match else None


@dataclass(frozen=True)
class SemanticSheetProfile:
    sheet_name: str
    dataframe: object
    header_row: int
    representative_column: int
    location_column: Optional[int]
    product_metrics: Dict[int, Dict[str, int]]
    score: int
    capability: str


class WorkbookSemanticLocator:
    """Locate authoritative workbook capabilities without physical coordinates."""

    MAX_HEADER_SCAN_ROWS = 80
    MAX_PROFILE_ROWS = 250
    HEADER_CONTEXT_ROWS = 5

    def __init__(self, importer):
        self.importer = importer
        self.workbook = importer.workbook or {}
        self._cache: Dict[str, Optional[SemanticSheetProfile]] = {}

    def _product_match(self, value):
        text = self.importer.clean_text(value)
        if not text:
            return None
        match = self.importer.resolve_product_match(text)
        if not match.get("matched"):
            return None
        obj = match.get("object")
        return getattr(obj, "id", None), obj

    def _header_product_count(self, frame, row_index: int) -> int:
        found = set()
        for value in frame.iloc[row_index].tolist():
            match = self._product_match(value)
            if match and match[0] is not None:
                found.add(match[0])
        return len(found)

    def _header_contexts(self, frame, header_row: int):
        """Build column context by carrying merged section labels horizontally."""
        start = max(0, header_row - self.HEADER_CONTEXT_ROWS + 1)
        carried = {}
        for row_index in range(start, header_row + 1):
            nonempty = sum(1 for value in frame.iloc[row_index].tolist() if self.importer.clean_text(value))
            current = ""
            section = ""
            for column in range(frame.shape[1]):
                raw = self.importer.clean_text(frame.iloc[row_index, column])
                token = _norm(raw)
                # A single report title is metadata, not a horizontal column group.
                if row_index != header_row and nonempty <= 1:
                    carried[(row_index, column)] = ""
                    continue
                if row_index == header_row:
                    if token and (
                        _has_any(token, TARGET_TOKENS)
                        or _has_any(token, BALANCE_TOKENS)
                        or _has_any(token, ACTUAL_TOKENS)
                    ):
                        section = token
                    parts = [part for part in (section, token) if part]
                    carried[(row_index, column)] = " | ".join(dict.fromkeys(parts))
                else:
                    if token:
                        current = token
                    carried[(row_index, column)] = current

        contexts = {}
        for column in range(frame.shape[1]):
            parts = []
            for row_index in range(start, header_row + 1):
                token = carried.get((row_index, column), "")
                if token and token not in parts:
                    parts.append(token)
            contexts[column] = " | ".join(parts)
        return contexts

    @staticmethod
    def _metric_family(context: str) -> Optional[str]:
        normalized = _norm(context)
        if _has_any(normalized, UNIT_TOKENS):
            return "unit"
        if _has_any(normalized, VALUE_TOKENS):
            return "tl"
        return None

    @staticmethod
    def _metric_phase(context: str) -> Optional[str]:
        normalized = _norm(context)
        if _has_any(normalized, TARGET_TOKENS):
            return "target"
        if _has_any(normalized, BALANCE_TOKENS):
            return "balance"
        if _has_any(normalized, ACTUAL_TOKENS):
            return "actual"
        return None

    def _classify_product_columns(self, frame, header_row: int, capability: str):
        contexts = self._header_contexts(frame, header_row)
        product_metrics: Dict[int, Dict[str, int]] = {}
        counts = {}
        for column in range(frame.shape[1]):
            match = self._product_match(frame.iloc[header_row, column])
            if not match or match[0] is None:
                continue
            product_id = match[0]
            context = contexts.get(column, "")
            family = self._metric_family(context)
            phase = self._metric_phase(context)
            metric = None
            if capability == "balance":
                if phase == "target" and family == "tl":
                    metric = "target_tl"
                elif phase == "actual" and family == "tl":
                    metric = "actual_tl"
                elif phase == "balance" and family == "tl":
                    metric = "balance_tl"
                elif phase == "balance" and family == "unit":
                    metric = "balance_unit"
            elif capability == "weekly":
                # MTD actuals are authoritative. A single-week section such as
                # "7. HAFTA" must never overwrite the cumulative period block.
                if phase == "actual" and family in {"tl", "unit"}:
                    if _has_any(_norm(context), WEEK_TOKENS):
                        continue
                    metric = f"actual_{family}"
            if not metric:
                continue
            existing = product_metrics.setdefault(product_id, {})
            key = (product_id, metric)
            counts[key] = counts.get(key, 0) + 1
            if metric not in existing:
                existing[metric] = column

        duplicate_metrics = [key for key, count in counts.items() if count > 1]
        return product_metrics, duplicate_metrics

    def _dimension_columns(self, frame, header_row: int, metric_columns):
        metric_columns = set(metric_columns)
        rep_tokens = getattr(self.importer, "REPRESENTATIVE_HEADERS", {
            "TEMSILCI", "REPRESENTATIVE", "TTS ISMI", "ADI SOYADI",
        })
        geo_tokens = (
            getattr(self.importer, "REGION_HEADERS", set())
            | getattr(self.importer, "PROVINCE_HEADERS", set())
            | getattr(self.importer, "BRICK_HEADERS", set())
            | {"TERRITORIES", "TERRITORY", "BOLGE", "REGION"}
        )
        start = min(header_row + 1, len(frame))
        stop = min(len(frame), start + self.MAX_PROFILE_ROWS)
        candidates = [column for column in range(frame.shape[1]) if column not in metric_columns]
        scored = []
        for column in candidates:
            rep_score = geo_score = 0
            header_text = " ".join(
                _norm(frame.iloc[row, column])
                for row in range(max(0, header_row - 2), header_row + 1)
            )
            if any(token in header_text for token in rep_tokens):
                rep_score += 20
            if any(token in header_text for token in geo_tokens):
                geo_score += 20
            for row_index in range(start, stop):
                value = self.importer.clean_text(frame.iloc[row_index, column])
                if not value:
                    continue
                normalized = _norm(value)
                if normalized == "NATIONAL":
                    rep_score += 5
                if _region_code(value):
                    geo_score += 4
                    rep_score += 1
                if self.importer._is_vacancy_representative(value):
                    rep_score += 5
                elif self.importer._is_probable_representative_name(value):
                    rep_score += 4
            scored.append((column, rep_score, geo_score))

        if not scored:
            raise ValueError("Semantic import: temsilci/bölge boyut kolonları bulunamadı.")

        representative_column = max(scored, key=lambda item: (item[1], -item[2]))[0]
        geo_candidates = [item for item in scored if item[0] != representative_column]
        location_column = (
            max(geo_candidates, key=lambda item: (item[2], -item[1]))[0]
            if geo_candidates and max(item[2] for item in geo_candidates) > 0
            else None
        )
        return representative_column, location_column

    def _candidate_profile(self, sheet_name, frame, capability: str):
        if frame is None or len(frame) < 2 or frame.shape[1] < 2:
            return None
        best = None
        for header_row in range(min(self.MAX_HEADER_SCAN_ROWS, len(frame))):
            product_count = self._header_product_count(frame, header_row)
            if product_count == 0:
                continue
            product_metrics, duplicates = self._classify_product_columns(frame, header_row, capability)
            if duplicates:
                continue
            if capability == "balance":
                target_count = sum("target_tl" in metrics for metrics in product_metrics.values())
                balance_tl_count = sum("balance_tl" in metrics for metrics in product_metrics.values())
                balance_unit_count = sum("balance_unit" in metrics for metrics in product_metrics.values())
                actual_count = sum("actual_tl" in metrics for metrics in product_metrics.values())
                if not target_count or not balance_tl_count or not balance_unit_count:
                    continue
                score = 100 + min(target_count, 20) + min(balance_tl_count, 20) + min(balance_unit_count, 20)
                score += min(actual_count, 10)
            else:
                tl_count = sum("actual_tl" in metrics for metrics in product_metrics.values())
                unit_count = sum("actual_unit" in metrics for metrics in product_metrics.values())
                if not tl_count or not unit_count:
                    continue
                score = 100 + min(tl_count, 30) + min(unit_count, 30)

            metric_columns = {
                column
                for metrics in product_metrics.values()
                for column in metrics.values()
            }
            try:
                representative_column, location_column = self._dimension_columns(
                    frame, header_row, metric_columns
                )
            except ValueError:
                continue
            national_count = sum(
                _norm(frame.iloc[row, representative_column]) == "NATIONAL"
                for row in range(header_row + 1, min(len(frame), header_row + 40))
            )
            if not national_count:
                continue
            score += 20
            profile = SemanticSheetProfile(
                sheet_name=str(sheet_name),
                dataframe=frame,
                header_row=header_row,
                representative_column=representative_column,
                location_column=location_column,
                product_metrics=product_metrics,
                score=score,
                capability=capability,
            )
            if best is None or profile.score > best.score:
                best = profile
        return best

    def locate(self, capability: str, *, required: bool = False):
        if capability in self._cache:
            profile = self._cache[capability]
            if required and profile is None:
                raise ValueError(f"Semantic import: {capability} kaynağı bulunamadı.")
            return profile

        candidates = []
        for sheet_name, frame in self.workbook.items():
            candidate = self._candidate_profile(sheet_name, frame, capability)
            if candidate:
                candidates.append(candidate)
        candidates.sort(key=lambda item: item.score, reverse=True)
        if len(candidates) >= 2 and candidates[0].score == candidates[1].score:
            raise ValueError(
                "Semantic import belirsiz kaynak: "
                f"{capability} için eşit güçlü sheetler: "
                f"{candidates[0].sheet_name}, {candidates[1].sheet_name}"
            )
        profile = candidates[0] if candidates else None
        self._cache[capability] = profile
        if required and profile is None:
            raise ValueError(f"Semantic import: {capability} kaynağı bulunamadı.")
        return profile

    @staticmethod
    def aggregate_identity(profile: SemanticSheetProfile, row):
        rep = row.iloc[profile.representative_column]
        loc = row.iloc[profile.location_column] if profile.location_column is not None else None
        rep_norm = _norm(rep)
        loc_norm = _norm(loc)
        if rep_norm == "NATIONAL":
            return "NATIONAL", "NATIONAL"
        rep_code = _region_code(rep)
        loc_code = _region_code(loc)
        if rep_code and (not loc_norm or rep_norm == loc_norm):
            return rep_code, str(rep).strip()
        if loc_code and rep_norm == loc_norm:
            return loc_code, str(rep).strip()
        return None

    def iter_data_rows(self, profile: SemanticSheetProfile):
        for row_index in range(profile.header_row + 1, len(profile.dataframe)):
            yield row_index, profile.dataframe.iloc[row_index]


def _profile_cache(importer):
    locator = getattr(importer, "_semantic_workbook_locator", None)
    if locator is None or locator.workbook is not (importer.workbook or {}):
        locator = WorkbookSemanticLocator(importer)
        importer._semantic_workbook_locator = locator
    return locator


def dynamic_bootstrap_vacancies(importer):
    """Bootstrap vacancy identities from semantic balance dimensions."""
    locator = _profile_cache(importer)
    profile = locator.locate("balance")
    if profile is None:
        return

    vacancies_by_region = {}
    for _row_index, row in locator.iter_data_rows(profile):
        vacancy_name = importer.clean_text(row.iloc[profile.representative_column])
        if not importer._is_vacancy_representative(vacancy_name):
            continue
        location = (
            importer.clean_text(row.iloc[profile.location_column])
            if profile.location_column is not None else ""
        )
        region, city = importer._region_context(location)
        if region:
            vacancies_by_region.setdefault(region, []).append((city, vacancy_name))

    for region, vacancies in vacancies_by_region.items():
        legacy = Representative.query.filter_by(rep_code=f"UNASSIGNED{region}").first()
        if legacy is None:
            continue
        city, vacancy_name = vacancies[-1]
        code = importer._vacancy_code(region, vacancy_name)
        if Representative.query.filter_by(rep_code=code).first() is None:
            legacy.rep_code = code
            legacy.rep_name = importer._vacancy_label(region, city, vacancy_name)
            legacy.city = city or legacy.city

    for _row_index, row in locator.iter_data_rows(profile):
        vacancy_name = importer.clean_text(row.iloc[profile.representative_column])
        if not importer._is_vacancy_representative(vacancy_name):
            continue
        location = (
            importer.clean_text(row.iloc[profile.location_column])
            if profile.location_column is not None else ""
        )
        importer._ensure_vacancy_representative(location, vacancy_name=vacancy_name)


def dynamic_apply_balance_summary(importer, year, month):
    profile = _profile_cache(importer).locate("balance")
    if profile is None:
        return

    locator = _profile_cache(importer)
    has_weekly_sales = locator.locate("weekly") is not None
    targets = {
        (item.representative_id, item.product_id): item
        for item in Target.query.filter_by(year=year, month=month).all()
    }
    summaries = {
        (item.representative_id, item.product_id): item
        for item in IMSSummary.query.filter_by(year=year, month=month).all()
    }
    products_by_id = {product.id: product for product in Product.query.all()}

    for _row_index, row in locator.iter_data_rows(profile):
        rep_name = importer.clean_text(row.iloc[profile.representative_column])
        if importer._is_vacancy_representative(rep_name):
            location = (
                importer.clean_text(row.iloc[profile.location_column])
                if profile.location_column is not None else ""
            )
            rep_id = importer._ensure_vacancy_representative(location, vacancy_name=rep_name)
            representative = db.session.get(Representative, rep_id)
        else:
            if not importer._is_probable_representative_name(rep_name):
                continue
            rep_match = importer.resolve_representative_match(rep_name)
            if not rep_match.get("matched"):
                continue
            representative = rep_match["object"]
            rep_id = representative.id

        location = (
            importer.clean_text(row.iloc[profile.location_column])
            if profile.location_column is not None else ""
        )
        match = _REGION_RE.match(_norm(location))
        if match and representative is not None:
            representative.region = match.group(1)
            if match.group(2):
                representative.city = match.group(2).strip()

        for product_id, columns in profile.product_metrics.items():
            target_value = (
                importer.safe_float(row.iloc[columns["target_tl"]])
                if "target_tl" in columns else None
            )
            actual_value = (
                importer.safe_float(row.iloc[columns["actual_tl"]])
                if "actual_tl" in columns else None
            )
            balance_tl = (
                importer.safe_float(row.iloc[columns["balance_tl"]])
                if "balance_tl" in columns else None
            )
            balance_unit = (
                importer.safe_float(row.iloc[columns["balance_unit"]])
                if "balance_unit" in columns else None
            )
            if target_value is None and actual_value is None:
                continue
            target = targets.get((rep_id, product_id))
            if target is None:
                target = Target(
                    year=year, month=month, quarter=importer.quarter_for(month),
                    representative_id=rep_id, product_id=product_id,
                )
                db.session.add(target)
                targets[(rep_id, product_id)] = target
            if target_value is not None:
                target.tl_target = target_value
            if balance_tl is not None and balance_unit not in (None, 0):
                net_unit_price = balance_tl / balance_unit
                if net_unit_price > 0:
                    target.unit_target = float(round(target.tl_target / net_unit_price))
            elif not target.unit_target:
                product = products_by_id.get(product_id)
                target.unit_target = TargetBoxCalculationService.unit_target(
                    target.tl_target, product.unit_price if product else 0,
                )

            summary = summaries.get((rep_id, product_id))
            if summary is not None:
                summary.target_tl = target.tl_target
                summary.target_unit = target.unit_target
            if not has_weekly_sales and actual_value is not None:
                target.tl_realization = actual_value
                target.realization_percent = (
                    round(target.tl_realization * 100 / target.tl_target, 2)
                    if target.tl_target else 0.0
                )
                if summary is not None:
                    summary.tl = target.tl_realization
                    summary.realization_percent = target.realization_percent
    db.session.flush()


def dynamic_apply_weekly_sales_summary(importer, year, month):
    locator = _profile_cache(importer)
    profile = locator.locate("weekly")
    if profile is None:
        return {"rows": 0, "matched_representatives": 0, "updated_values": 0}

    targets = {
        (item.representative_id, item.product_id): item
        for item in Target.query.filter_by(year=year, month=month).all()
    }
    summaries = {
        (item.representative_id, item.product_id): item
        for item in IMSSummary.query.filter_by(year=year, month=month).all()
    }
    rows = matched_representatives = updated_values = 0
    for _row_index, row in locator.iter_data_rows(profile):
        rep_name = importer.clean_text(row.iloc[profile.representative_column])
        location = (
            importer.clean_text(row.iloc[profile.location_column])
            if profile.location_column is not None else ""
        )
        if importer._is_vacancy_representative(rep_name):
            rep_id = importer._ensure_vacancy_representative(location, vacancy_name=rep_name)
        elif importer._is_probable_representative_name(rep_name):
            rep_match = importer.resolve_representative_match(rep_name)
            if not rep_match.get("matched"):
                continue
            rep_id = rep_match["object"].id
        else:
            continue

        rows += 1
        matched_representatives += 1
        for product_id, columns in profile.product_metrics.items():
            summary = summaries.get((rep_id, product_id))
            target = targets.get((rep_id, product_id))
            if summary is None:
                continue
            if "actual_tl" in columns:
                value = importer.safe_float(row.iloc[columns["actual_tl"]])
                summary.tl = value
                if target is not None:
                    target.tl_realization = value
            if "actual_unit" in columns:
                value = importer.safe_float(row.iloc[columns["actual_unit"]])
                summary.unit = value
                if target is not None:
                    target.unit_realization = value
            if target is not None:
                target.realization_percent = (
                    round(summary.tl * 100 / target.tl_target, 2)
                    if target.tl_target else 0.0
                )
                summary.target_tl = target.tl_target
                summary.target_unit = target.unit_target
                summary.realization_percent = target.realization_percent
            updated_values += 1
    db.session.flush()
    return {
        "rows": rows,
        "matched_representatives": matched_representatives,
        "updated_values": updated_values,
    }


def dynamic_persist_dashboard_metrics(importer, year, month):
    """Persist legacy dashboard rows using the same semantic profiles."""
    if not importer.upload or not importer.workbook:
        return

    locator = _profile_cache(importer)

    def upsert(sheet_name, sheet_type, product_id, unit, tl, metadata,
               representative="NATIONAL", territory=None):
        record = IMSRawData.query.filter_by(
            upload_id=importer.upload.id,
            sheet_type=sheet_type,
            product_id=product_id,
            representative=representative,
            territory=territory,
        ).first()
        values = dict(
            year=year, month=month, quarter=importer.quarter_for(month),
            week_number=importer.upload.week_number, sheet_name=sheet_name,
            sheet_type=sheet_type, source_row=0, product_id=product_id,
            representative=representative, territory=territory,
            unit=float(unit or 0), tl=float(tl or 0),
            raw_json=importer._json_dump(metadata),
        )
        if record is None:
            db.session.add(IMSRawData(upload_id=importer.upload.id, **values))
        else:
            for key, value in values.items():
                setattr(record, key, value)

    balance = locator.locate("balance")
    if balance is not None:
        for _row_index, row in locator.iter_data_rows(balance):
            identity = locator.aggregate_identity(balance, row)
            if not identity:
                continue
            territory, representative = identity
            for product_id, columns in balance.product_metrics.items():
                target_tl = (
                    importer.safe_float(row.iloc[columns["target_tl"]])
                    if "target_tl" in columns else 0.0
                )
                actual_tl = (
                    importer.safe_float(row.iloc[columns["actual_tl"]])
                    if "actual_tl" in columns else 0.0
                )
                metadata = {"target_tl": target_tl, "actual_tl": actual_tl}
                upsert(
                    balance.sheet_name,
                    "dashboard_balance_national" if territory == "NATIONAL" else "dashboard_balance_region",
                    product_id, target_tl, actual_tl, metadata,
                    representative=representative,
                    territory=None if territory == "NATIONAL" else territory,
                )

    weekly = locator.locate("weekly")
    if weekly is not None:
        for _row_index, row in locator.iter_data_rows(weekly):
            identity = locator.aggregate_identity(weekly, row)
            if not identity:
                continue
            territory, representative = identity
            for product_id, columns in weekly.product_metrics.items():
                actual_tl = (
                    importer.safe_float(row.iloc[columns["actual_tl"]])
                    if "actual_tl" in columns else 0.0
                )
                actual_unit = (
                    importer.safe_float(row.iloc[columns["actual_unit"]])
                    if "actual_unit" in columns else 0.0
                )
                metadata = {"actual_tl": actual_tl, "actual_unit": actual_unit}
                upsert(
                    weekly.sheet_name,
                    "dashboard_weekly_units" if territory == "NATIONAL" else "dashboard_weekly_region",
                    product_id, actual_unit, actual_tl, metadata,
                    representative=representative,
                    territory=None if territory == "NATIONAL" else territory,
                )

    from app.services.official_aggregate_service import persist_official_aggregates
    persist_official_aggregates(importer, year, month)
    db.session.flush()


def dynamic_persist_official_aggregates(importer, year, month):
    """Persist NATIONAL/region aggregates from semantic balance/weekly sources."""
    if not importer.upload or not importer.workbook:
        return {"targets": 0, "actuals": 0}

    import app.services.official_aggregate_service as official

    locator = _profile_cache(importer)
    targets_written = actuals_written = 0

    balance = locator.locate("balance")
    if balance is not None:
        for _row_index, row in locator.iter_data_rows(balance):
            identity = locator.aggregate_identity(balance, row)
            if not identity:
                continue
            territory, representative = identity
            for product_id, columns in balance.product_metrics.items():
                if "target_tl" not in columns:
                    continue
                target_tl = importer.safe_float(row.iloc[columns["target_tl"]])
                balance_tl = (
                    importer.safe_float(row.iloc[columns["balance_tl"]])
                    if "balance_tl" in columns else 0.0
                )
                balance_unit = (
                    importer.safe_float(row.iloc[columns["balance_unit"]])
                    if "balance_unit" in columns else 0.0
                )
                target_unit = (
                    target_tl / (balance_tl / balance_unit)
                    if balance_tl and balance_unit and (balance_tl / balance_unit) > 0
                    else 0.0
                )
                official._upsert(
                    importer, year, month, balance.sheet_name, official.TARGET_TYPE,
                    territory, representative, product_id, target_unit, target_tl,
                    {
                        "target_tl": target_tl,
                        "target_unit": target_unit,
                        "balance_tl": balance_tl,
                        "balance_unit": balance_unit,
                        "source": "semantic balance aggregate row",
                    },
                )
                targets_written += 1

    weekly = locator.locate("weekly")
    if weekly is not None:
        for _row_index, row in locator.iter_data_rows(weekly):
            identity = locator.aggregate_identity(weekly, row)
            if not identity:
                continue
            territory, representative = identity
            for product_id, columns in weekly.product_metrics.items():
                actual_tl = (
                    importer.safe_float(row.iloc[columns["actual_tl"]])
                    if "actual_tl" in columns else 0.0
                )
                actual_unit = (
                    importer.safe_float(row.iloc[columns["actual_unit"]])
                    if "actual_unit" in columns else 0.0
                )
                official._upsert(
                    importer, year, month, weekly.sheet_name, official.ACTUAL_TYPE,
                    territory, representative, product_id, actual_unit, actual_tl,
                    {
                        "actual_tl": actual_tl,
                        "actual_unit": actual_unit,
                        "source": "semantic cumulative actual aggregate row",
                    },
                )
                actuals_written += 1

    db.session.flush()
    reconciliation = official.reconcile_national_regions(importer)
    return {
        "targets": targets_written,
        "actuals": actuals_written,
        "reconciliation": reconciliation,
    }


def dynamic_competition_structure(service, sheet_name):
    """Parse every competition sheet from content; never from fixed row numbers."""
    if not service._workbook:
        raise ValueError("Çalışma kitabı yüklenmemiş.")
    actual_map = {
        service._normalize_sheet_name(name): name for name in service._workbook.sheetnames
    }
    norm_target = service._normalize_sheet_name(sheet_name)
    if norm_target not in actual_map:
        raise ValueError(f"Sayfa bulunamadı: '{sheet_name}'")
    original = actual_map[norm_target]
    sheet = service._workbook[original]
    period_type, year, month = service._discover_metadata(sheet)

    max_row = sheet.max_row or 0
    max_col = sheet.max_column or 0
    best = None
    for row in range(1, min(max_row, 80) + 1):
        values = [service._get_cell_value(sheet, row, column) for column in range(1, max_col + 1)]
        normalized = [service._normalize_turkish_text(value) for value in values]
        product_columns = {}
        product_count = 0
        for column, value in enumerate(values, start=1):
            text = str(value).strip() if value is not None else ""
            if not text or service._is_meta_col(text):
                continue
            numeric_below = 0
            for data_row in range(row + 1, min(max_row, row + 8) + 1):
                cell = service._get_cell_value(sheet, data_row, column)
                if isinstance(cell, (int, float)):
                    numeric_below += 1
            if numeric_below:
                product_columns[column] = text
                product_count += 1

        dimension_candidates = []
        for column, label in enumerate(normalized, start=1):
            if any(token in label for token in (
                "IAM BRICK", "BRICK", "TERRITOR", "SUBTERRITOR", "TTS ISMI",
                "TEMSILCI", "REPRESENTATIVE", "BOLGE", "REGION", "NATIONAL",
            )):
                dimension_candidates.append(column)

        if product_count and len(dimension_candidates) < 2:
            inferred = []
            for column in range(1, max_col + 1):
                if column in product_columns:
                    continue
                score = 0
                for data_row in range(row + 1, min(max_row, row + 50) + 1):
                    value = str(service._get_cell_value(sheet, data_row, column) or "").strip()
                    normalized_value = service._normalize_turkish_text(value)
                    if normalized_value == "NATIONAL":
                        score += 5
                    if re.match(r"^\s*\d{3}\b", normalized_value):
                        score += 4
                    if value and " " in value and not re.search(r"\d", value):
                        score += 1
                if score:
                    inferred.append((score, column))
            inferred.sort(reverse=True)
            dimension_candidates.extend(
                column for _score, column in inferred[:2]
                if column not in dimension_candidates
            )

        if product_count == 0 or not dimension_candidates:
            continue
        score = product_count * 4 + len(dimension_candidates) * 3
        if best is None or score > best[0]:
            best = (score, row, product_columns, dimension_candidates)

    if best is None:
        raise ValueError(f"{original}: rekabet başlığı/dimension yapısı semantik olarak bulunamadı.")

    _score, header_row, product_columns, dimensions = best
    metric_columns = set(product_columns)

    def dimension_score(column):
        territory_score = sub_score = 0
        for data_row in range(header_row + 1, min(max_row, header_row + 250) + 1):
            value = str(service._get_cell_value(sheet, data_row, column) or "").strip()
            normalized = service._normalize_turkish_text(value)
            if re.match(r"^\s*\d{3}\b", normalized):
                territory_score += 4
            if normalized == "NATIONAL":
                sub_score += 5
            if value and " " in value and not re.search(r"\d", value):
                sub_score += 1
        return territory_score, sub_score

    ranked = [(column, *dimension_score(column)) for column in dimensions if column not in metric_columns]
    if not ranked:
        raise ValueError(f"{original}: rekabet dimension kolonları bulunamadı.")
    territory_column = max(ranked, key=lambda item: (item[1], -item[2]))[0]
    sub_candidates = [item for item in ranked if item[0] != territory_column]
    subterritory_column = (
        max(sub_candidates, key=lambda item: (item[2], -item[1]))[0]
        if sub_candidates else territory_column
    )
    data_start = None
    for row in range(header_row + 1, max_row + 1):
        territory = service._get_cell_value(sheet, row, territory_column)
        subterritory = service._get_cell_value(sheet, row, subterritory_column)
        if str(territory or "").strip() or str(subterritory or "").strip():
            data_start = row
            break
    if data_start is None:
        raise ValueError(f"{original}: rekabet veri başlangıcı bulunamadı.")
    data_end = service._find_data_end(sheet, data_start)

    original_groups = service._extract_product_groups(sheet, header_row)
    dimension_set = {item[0] for item in ranked}
    product_columns = {
        column: name for column, name in product_columns.items()
        if column not in dimension_set
    }
    product_groups = {
        group: [(name, column) for name, column in products if column in product_columns]
        for group, products in original_groups.items()
    }
    product_groups = {group: products for group, products in product_groups.items() if products}
    if not product_columns or not product_groups:
        raise ValueError(f"{original}: rekabet ürün kolonları semantik olarak bulunamadı.")

    return {
        "sheet_name": original,
        "sheet_type": service.get_sheet_type(original),
        "period_type": period_type,
        "year": year,
        "month": month,
        "header_row": header_row,
        "data_start_row": data_start,
        "data_end_row": data_end,
        "max_columns": max_col,
        "territory_column": territory_column,
        "subterritory_column": subterritory_column,
        "product_columns": product_columns,
        "product_groups": product_groups,
    }


def install_dynamic_import_contract():
    """Install semantic implementations while preserving all business rules."""
    from app.services.competition_import_service import CompetitionImportService
    from app.services.ims_import_service import IMSImportService
    import app.services.official_aggregate_service as official

    if getattr(IMSImportService, "_dynamic_import_contract_installed", False):
        return

    IMSImportService.bootstrap_vacancy_representatives_from_balance = dynamic_bootstrap_vacancies
    IMSImportService.apply_balance_summary = dynamic_apply_balance_summary
    IMSImportService.apply_weekly_sales_summary = dynamic_apply_weekly_sales_summary
    IMSImportService.persist_national_dashboard_metrics = dynamic_persist_dashboard_metrics
    CompetitionImportService._parse_sheet_structure = dynamic_competition_structure
    official.persist_official_aggregates = dynamic_persist_official_aggregates
    IMSImportService._dynamic_import_contract_installed = True
