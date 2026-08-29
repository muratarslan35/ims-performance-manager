"""Make BAKİYE remaining boxes authoritative for representative IMS unit actuals.

The BAKİYE workbook uses a multi-row header: metric groups (HEDEF / ÇIKIŞ /
MF'siz KUTU BAKİYE) and product names can live on different rows. The legacy
``apply_balance_summary`` path assumed both labels shared one cell, so the
remaining-box columns were not resolved and TTS units later won by fallback.

This adapter is deliberately narrow. It runs immediately after the existing
balance summary logic and before weekly TTS application. It changes only
``Target.unit_realization`` and ``IMSSummary.unit`` for representative/product
pairs with an explicit numeric MF'siz KUTU BAKİYE cell. TL, targets, prime,
competition and P2/P1 precedence are untouched. Numeric zero is authoritative.
"""
from __future__ import annotations

import math

from app.extensions import db
from app.models import IMSSummary, Target
from app.services.alias_service import AliasService


def _numeric_or_none(service, value):
    """Return a real numeric cell, preserving zero while rejecting blanks."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str) and AliasService.normalize(value) in {"", "NAN", "NONE", "-"}:
        return None
    return float(service.safe_float(value))


def _section_for(value):
    normalized = AliasService.normalize(value)
    if "BAKIYE" in normalized and ("KUTU" in normalized or "UNIT" in normalized or "ADET" in normalized):
        return "balance_unit"
    if "BAKIYE" in normalized:
        return "balance_tl"
    if "HEDEF" in normalized or "TARGET" in normalized:
        return "target"
    if "CIKIS" in normalized or "ÇIKIŞ" in normalized:
        return "actual"
    return None


def _discover_balance_columns(service, frame):
    """Discover metric groups and products independently across header rows."""
    max_rows = min(12, len(frame))
    if max_rows == 0:
        return {}, 0

    best_metric_row = None
    best_metric_score = -1
    best_sections = None
    for row_index in range(max_rows):
        sections = {}
        current = None
        explicit = set()
        for column in range(frame.shape[1]):
            found = _section_for(service.clean_text(frame.iloc[row_index, column]))
            if found is not None:
                current = found
                explicit.add(found)
            sections[column] = current
        score = len(explicit) + (4 if "balance_unit" in explicit else 0) + (2 if "target" in explicit else 0)
        if score > best_metric_score:
            best_metric_score = score
            best_metric_row = row_index
            best_sections = sections

    if best_metric_row is None or not best_sections or "balance_unit" not in set(best_sections.values()):
        return {}, 0

    product_rows = {}
    best_product_row = None
    best_product_count = 0
    for row_index in range(max_rows):
        matches = {}
        for column in range(frame.shape[1]):
            match = service.resolve_product_match(service.clean_text(frame.iloc[row_index, column]))
            if match.get("matched"):
                matches[column] = int(match["object"].id)
        product_rows[row_index] = matches
        if len(matches) > best_product_count:
            best_product_count = len(matches)
            best_product_row = row_index

    if best_product_row is None or best_product_count == 0:
        return {}, 0

    mapping = {}
    selected_products = product_rows[best_product_row]
    for column, section in best_sections.items():
        if section is None:
            continue
        product_id = selected_products.get(column)
        if product_id is None:
            # Merged/multi-row headers can place the product one row above or
            # below the dominant product row. Search the same column only.
            for row_index in range(max_rows):
                product_id = product_rows[row_index].get(column)
                if product_id is not None:
                    break
        if product_id is not None:
            mapping[column] = (int(product_id), section)

    return mapping, max(best_metric_row, best_product_row) + 1


def _apply_authoritative_balance_units(service, year, month):
    sheet_name = next(
        (name for name in (service.workbook or {}) if "BAKIYE" in AliasService.normalize(name)),
        None,
    )
    if not sheet_name:
        return 0

    frame = service.workbook[sheet_name]
    column_map, data_start = _discover_balance_columns(service, frame)
    balance_columns = {
        column: product_id
        for column, (product_id, section) in column_map.items()
        if section == "balance_unit"
    }
    if not balance_columns:
        return 0

    targets = {
        (int(item.representative_id), int(item.product_id)): item
        for item in Target.query.filter_by(year=int(year), month=int(month)).all()
    }
    summaries = {
        (int(item.representative_id), int(item.product_id)): item
        for item in IMSSummary.query.filter_by(year=int(year), month=int(month)).all()
        if item.representative_id is not None and item.product_id is not None
    }

    changed = 0
    for _, row in frame.iloc[data_start:].iterrows():
        rep_name = service.clean_text(row.iloc[1]) if frame.shape[1] > 1 else ""
        if not rep_name:
            continue
        if service._is_vacancy_representative(rep_name):
            location = service.clean_text(row.iloc[0]) if frame.shape[1] > 0 else ""
            rep_id = service._ensure_vacancy_representative(location, vacancy_name=rep_name)
        else:
            # Do not reject valid BAKİYE names through the generic probable-name
            # heuristic. The authoritative resolver is stricter and already
            # returns unmatched for headers/subtotals/noise rows.
            match = service.resolve_representative_match(rep_name)
            if not match.get("matched"):
                continue
            rep_id = int(match["object"].id)

        for column, product_id in balance_columns.items():
            balance_unit = _numeric_or_none(service, row.iloc[column])
            if balance_unit is None:
                continue
            key = (int(rep_id), int(product_id))
            target = targets.get(key)
            if target is None:
                continue

            actual_unit = float(target.unit_target or 0.0) - float(balance_unit)
            target.unit_realization = actual_unit
            service._balance_unit_actual_keys.add(key)
            summary = summaries.get(key)
            if summary is not None:
                summary.unit = actual_unit
            changed += 1

    if changed:
        db.session.flush()
    return changed


def install_balance_unit_authority() -> None:
    """Install the narrow post-balance/pre-TTS invariant once per process."""
    from app.services.ims_import_service import IMSImportService

    if getattr(IMSImportService, "_balance_unit_authority_installed", False):
        return

    original_apply_balance_summary = IMSImportService.apply_balance_summary

    def apply_balance_summary_with_unit_authority(self, year, month):
        result = original_apply_balance_summary(self, year, month)
        changed = _apply_authoritative_balance_units(self, year, month)
        self.statistics["balance_unit_authority_rows"] = changed
        return result

    IMSImportService.apply_balance_summary = apply_balance_summary_with_unit_authority
    IMSImportService._balance_unit_authority_installed = True
