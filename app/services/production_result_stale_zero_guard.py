"""Narrow production guard for departed representatives and vacancy succession.

Approved production workbooks can retain a departed real representative name in
KUTU while the TL sheet already carries the successor vacancy identity.  We keep
this fail-closed: a departed KUTU row can only bridge to a current vacancy when
all actuals are exactly zero and workbook-owned TL/KUTU target price signatures
prove one unique same-region vacancy.  Unknown, non-zero, ambiguous, or current
rows remain rejected.
"""

from statistics import median

from app.models import Representative, Target
from app.services.alias_service import AliasService
from app.services.production_result_import_service import (
    ProductionResultImportService,
    ProductionWorkbookValidationError,
)


_PRICE_REL_TOLERANCE = 0.002
_PRICE_ABS_TOLERANCE = 0.05
_TARGET_REL_TOLERANCE = 0.002
_TARGET_ABS_TOLERANCE = 1.0
_MIN_PRICE_WITNESSES = 3


def _region_key(value):
    return AliasService.normalize(value).split(" ", 1)[0]


def _unique_departed_identity(service, raw_name, raw_region):
    name = AliasService.normalize(raw_name)
    region = _region_key(raw_region)
    if not name or not region:
        return None

    matches = []
    for representative in Representative.query.filter_by(active=False).all():
        if str(representative.rep_code or "").upper().startswith("UNASSIGNED"):
            continue
        if _region_key(representative.region) != region:
            continue
        labels = {
            AliasService.normalize(value)
            for value in (
                representative.rep_name,
                representative.rep_code,
                representative.ims_code,
            )
            if value
        }
        if name in labels:
            matches.append(representative)

    if len(matches) != 1:
        return None

    representative = matches[0]
    has_current_target = (
        Target.query.filter_by(
            year=service.year,
            month=service.month,
            representative_id=representative.id,
        ).first()
        is not None
    )
    return None if has_current_target else representative


def _safe_zero_departed_box_row(
    service,
    sheet,
    row_number,
    layout,
    metric,
    raw_name,
    raw_region,
):
    if service._metric(metric) != "KUTU":
        return None
    departed = _unique_departed_identity(service, raw_name, raw_region)
    if departed is None:
        return None

    values = service._read_metric_values(sheet, row_number, layout, "eski pasif temsilci")
    if values["total_actual"] != 0 or any(value != 0 for value in values["values"]):
        return None
    return {
        "departed_id": departed.id,
        "departed_name": departed.rep_name,
        "region": _region_key(raw_region),
        "values": values,
    }


def _row_value(row, product_id, key):
    try:
        position = row["product_ids"].index(product_id)
    except ValueError:
        return None
    return float(row[key][position])


def _workbook_price_signature(tl_rows, unit_rows, product_ids):
    """Infer target TL/unit prices only from representatives present in both sheets."""
    common_ids = set(tl_rows) & set(unit_rows)
    signature = {}
    for product_id in product_ids:
        ratios = []
        for representative_id in common_ids:
            tl_row = tl_rows[representative_id]
            unit_row = unit_rows[representative_id]
            tl_target = _row_value(tl_row, product_id, "targets")
            unit_target = _row_value(unit_row, product_id, "targets")
            if tl_target is None or unit_target is None or unit_target <= 0:
                continue
            ratios.append(tl_target / unit_target)
        if len(ratios) < _MIN_PRICE_WITNESSES:
            return None
        price = median(ratios)
        tolerance = max(_PRICE_ABS_TOLERANCE, abs(price) * _PRICE_REL_TOLERANCE)
        if any(abs(value - price) > tolerance for value in ratios):
            return None
        signature[product_id] = price
    return signature


def _candidate_matches_signature(tl_row, stale_values, signature):
    if set(tl_row["product_ids"]) != set(stale_values["product_ids"]):
        return False
    for product_id in stale_values["product_ids"]:
        unit_target = _row_value(stale_values, product_id, "targets")
        tl_target = _row_value(tl_row, product_id, "targets")
        if unit_target is None or tl_target is None:
            return False
        expected = unit_target * signature[product_id]
        tolerance = max(_TARGET_ABS_TOLERANCE, abs(tl_target) * _TARGET_REL_TOLERANCE)
        if abs(expected - tl_target) > tolerance:
            return False
    return True


def _reconcile_departed_rows_to_vacancies(service, unit_rows, stale_rows):
    tl_rows = getattr(service, "_stale_guard_tl_rows", None)
    if not tl_rows or not stale_rows:
        return unit_rows

    tl_only = set(tl_rows) - set(unit_rows)
    used = set()
    for stale in stale_rows:
        product_ids = stale["values"]["product_ids"]
        signature = _workbook_price_signature(tl_rows, unit_rows, product_ids)
        if signature is None:
            raise ProductionWorkbookValidationError(
                "Eski temsilci kutu satırı için workbook hedef fiyat imzası güvenli biçimde doğrulanamadı."
            )

        matches = []
        for representative_id in sorted(tl_only - used):
            representative = db.session.get(Representative, representative_id)
            if representative is None:
                continue
            if not str(representative.rep_code or "").upper().startswith("UNASSIGNED"):
                continue
            if _region_key(representative.region) != stale["region"]:
                continue
            if (
                Target.query.filter_by(
                    year=service.year,
                    month=service.month,
                    representative_id=representative.id,
                ).count()
                != len(product_ids)
            ):
                continue
            if _candidate_matches_signature(
                tl_rows[representative_id], stale["values"], signature
            ):
                matches.append(representative_id)

        if len(matches) != 1:
            raise ProductionWorkbookValidationError(
                f"{stale['departed_name']} eski kutu satırının güncel boş kadro devamlılığı "
                "tekil olarak kanıtlanamadı."
            )

        successor_id = matches[0]
        unit_rows[successor_id] = stale["values"]
        used.add(successor_id)
    return unit_rows


def install_production_result_stale_zero_guard():
    """Patch representative collection while preserving downstream reconciliation gates."""
    if getattr(ProductionResultImportService, "_stale_zero_guard_installed", False):
        return

    def guarded_read_sheet(self, sheet, metric):
        layout = self._layout(sheet, metric)
        rows, unresolved, duplicates, stale_rows = {}, [], [], []
        metric_name = self._metric(metric)
        for row_number in range(layout["header_row"] + 1, sheet.max_row + 1):
            raw_name = sheet.cell(row_number, layout["name_column"]).value
            raw_region = sheet.cell(row_number, layout["region_column"]).value
            label = AliasService.normalize(raw_name)
            if not label or label == "NATIONAL" or self._is_region(label):
                continue

            representative = self._match_representative(raw_name, raw_region)
            if representative is None:
                stale = _safe_zero_departed_box_row(
                    self,
                    sheet,
                    row_number,
                    layout,
                    metric_name,
                    raw_name,
                    raw_region,
                )
                if stale is not None:
                    stale_rows.append(stale)
                    continue
                unresolved.append(str(raw_name).strip())
                continue

            if representative.id in rows:
                duplicates.append(representative.rep_name)
                continue
            rows[representative.id] = self._read_metric_values(
                sheet, row_number, layout, "temsilci"
            )

        if unresolved:
            raise ProductionWorkbookValidationError(
                "Eşleşmeyen temsilci/boş kadro satırları: "
                + ", ".join(sorted(set(unresolved))[:10])
            )
        if duplicates:
            raise ProductionWorkbookValidationError(
                "Bir temsilci birden fazla kez bulundu: "
                + ", ".join(sorted(set(duplicates))[:10])
            )

        if metric_name == "TL":
            self._stale_guard_tl_rows = dict(rows)
        elif stale_rows and getattr(self, "_stale_guard_tl_rows", None):
            rows = _reconcile_departed_rows_to_vacancies(self, rows, stale_rows)
        return rows

    ProductionResultImportService._read_sheet = guarded_read_sheet
    ProductionResultImportService._stale_zero_guard_installed = True


# Local import avoids widening the model imports used during module initialization.
from app.extensions import db
