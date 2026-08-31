"""Direct representative TL authority for proven compact TTS IMS workbooks.

Wide IMS workbooks keep the existing BAKIYE / TTS HAFTALIK semantic path.
Some compact March workbooks instead carry three repeated product blocks in
``TTS ÇIKIŞLARI``: target TL, cumulative actual TL and realization %.  Brick
facts remain authoritative for brick analytics, but representative/product
period actuals must come from this direct TTS block when it is present.
"""

import math
import re

from app.extensions import db
from app.models import IMSSummary, Target
from app.services.alias_service import AliasService
from app.services.ims_import_service import IMSImportService

_INSTALLED = False
_ORIGINAL_APPLY_WEEKLY = None


def _blank(value):
    if value is None:
        return True
    return isinstance(value, float) and math.isnan(value)


def _region_subtotal(value):
    normalized = AliasService.normalize(value)
    return bool(re.match(r"^\d{3}\s+", normalized))


def _compact_layout(service):
    """Return a validated compact TTS layout, otherwise ``None``.

    Detection is content based.  It deliberately requires three repeated
    product groups terminated by TOPLAM so ordinary/wide sales sheets cannot
    enter this fallback.
    """
    for sheet_name, frame in (service.workbook or {}).items():
        normalized_name = AliasService.normalize(sheet_name)
        if "TTS" not in normalized_name or "CIKIS" not in normalized_name or "HAFTALIK" in normalized_name:
            continue
        if len(frame.index) < 3 or len(frame.columns) < 6:
            continue

        title = AliasService.normalize(
            " ".join(service.clean_text(value) for value in frame.iloc[0].tolist() if service.clean_text(value))
        )
        if "HEDEF" not in title and "TARGET" not in title:
            continue

        for header_row in range(1, min(6, len(frame.index))):
            groups = []
            current = {}
            total_count = 0
            for column in range(frame.shape[1]):
                label = service.clean_text(frame.iloc[header_row, column])
                normalized = AliasService.normalize(label)
                if normalized in {"TOPLAM", "TOTAL", "GENEL TOPLAM", "GRAND TOTAL"}:
                    groups.append(current)
                    current = {}
                    total_count += 1
                    continue
                match = service.resolve_product_match(label) if label else {"matched": False}
                if match.get("matched"):
                    current[int(match["object"].id)] = column
            if current:
                groups.append(current)

            if total_count < 3 or len(groups) < 3:
                continue
            target_columns, actual_columns, percent_columns = groups[:3]
            target_ids = set(target_columns)
            if len(target_ids) < 2 or target_ids != set(actual_columns) or target_ids != set(percent_columns):
                continue

            first_metric = min(target_columns.values())
            identity_candidates = range(0, first_metric)
            rep_scores = {}
            for column in identity_candidates:
                score = 0
                for row_index in range(header_row + 1, min(len(frame.index), header_row + 80)):
                    raw = service.clean_text(frame.iloc[row_index, column])
                    if not raw or AliasService.normalize(raw) == "NATIONAL" or _region_subtotal(raw):
                        continue
                    match = service.resolve_representative_match(raw)
                    if match.get("matched"):
                        score += 1
                rep_scores[column] = score
            if not rep_scores or max(rep_scores.values()) == 0:
                continue
            representative_column = max(rep_scores, key=rep_scores.get)
            region_column = representative_column - 1 if representative_column > 0 else None
            return {
                "sheet_name": sheet_name,
                "frame": frame,
                "header_row": header_row,
                "representative_column": representative_column,
                "region_column": region_column,
                "actual_columns": actual_columns,
                "product_ids": sorted(target_ids),
            }
    return None


def apply_compact_tts_representative_actuals(service, year, month):
    layout = _compact_layout(service)
    if not layout:
        return {"rows": 0, "matched_representatives": 0, "updated_values": 0, "source": "unavailable"}

    frame = layout["frame"]
    summaries = {
        (int(row.representative_id), int(row.product_id)): row
        for row in IMSSummary.query.filter_by(
            upload_id=service.upload.id,
            year=year,
            month=month,
        ).all()
    }
    targets = {
        (int(row.representative_id), int(row.product_id)): row
        for row in Target.query.filter_by(year=year, month=month).all()
    }

    updated = 0
    matched_representatives = set()
    missing_summary = []
    source_rows = 0
    for row_index in range(layout["header_row"] + 1, len(frame.index)):
        rep_name = service.clean_text(frame.iloc[row_index, layout["representative_column"]])
        normalized_rep = AliasService.normalize(rep_name)
        if not rep_name or normalized_rep == "NATIONAL" or _region_subtotal(rep_name):
            continue

        rep_match = service.resolve_representative_match(rep_name)
        rep_id = int(rep_match["object"].id) if rep_match.get("matched") else None
        if rep_id is None and service._is_vacancy_representative(rep_name):
            location = ""
            if layout["region_column"] is not None:
                location = service.clean_text(frame.iloc[row_index, layout["region_column"]])
            rep_id = int(service._ensure_vacancy_representative(location, vacancy_name=rep_name))
        if rep_id is None:
            # Existing import validation remains responsible for unresolved
            # identities.  This overlay never guesses a representative.
            continue

        source_rows += 1
        matched_representatives.add(rep_id)
        for product_id, column in layout["actual_columns"].items():
            raw_value = frame.iloc[row_index, column]
            if _blank(raw_value):
                # Blank means the compact source did not provide this metric.
                # Numeric zero is intentionally NOT blank and is authoritative.
                continue
            actual_tl = float(service.safe_float(raw_value))
            key = (rep_id, int(product_id))
            summary = summaries.get(key)
            if summary is None:
                missing_summary.append(key)
                continue

            summary.tl = actual_tl
            target = targets.get(key)
            target_tl = float(target.tl_target or 0.0) if target is not None else float(summary.target_tl or 0.0)
            realization = round(actual_tl * 100.0 / target_tl, 2) if target_tl else 0.0
            summary.realization_percent = realization
            if target is not None:
                target.tl_realization = actual_tl
                target.realization_percent = realization
            updated += 1

    if missing_summary:
        preview = ", ".join(f"{rep_id}:{product_id}" for rep_id, product_id in missing_summary[:10])
        raise ValueError(
            "Compact TTS direct actual authority could not find canonical summary rows: "
            f"count={len(missing_summary)} preview={preview}"
        )

    service.statistics["compact_tts_direct_actual_rows"] = source_rows
    service.statistics["compact_tts_direct_actual_values"] = updated
    db.session.flush()
    return {
        "rows": source_rows,
        "matched_representatives": len(matched_representatives),
        "updated_values": updated,
        "source": "compact_tts_direct_actual",
        "sheet_name": layout["sheet_name"],
    }


def _apply_weekly_sales_summary(self, year, month):
    result = _ORIGINAL_APPLY_WEEKLY(self, year, month)
    # A real wide TTS HAFTALIK layer remains authoritative and unchanged.
    if result and int(result.get("updated_values") or 0) > 0:
        return result
    compact = apply_compact_tts_representative_actuals(self, year, month)
    return compact if compact.get("updated_values") else result


def install_compact_tts_import_actual_authority():
    global _INSTALLED, _ORIGINAL_APPLY_WEEKLY
    if _INSTALLED:
        return
    _ORIGINAL_APPLY_WEEKLY = IMSImportService.apply_weekly_sales_summary
    IMSImportService.apply_weekly_sales_summary = _apply_weekly_sales_summary
    _INSTALLED = True
