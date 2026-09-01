"""Narrow guard for stale departed representative rows in production KUTU sheets.

Some approved production workbooks retain a departed real representative in the
KUTU roster even after the person has left the current target scope.  Such a
row must never be reassigned to another representative.  It may be ignored only
when it is provably non-contributing: KUTU metric, unique inactive historical
identity in the same region, no target in the selected period, and every actual
value (including the total) is exactly zero.

All unknown, ambiguous, current-period, TL, or non-zero rows remain fail-closed.
"""

from app.models import Representative, Target
from app.services.alias_service import AliasService
from app.services.production_result_import_service import (
    ProductionResultImportService,
    ProductionWorkbookValidationError,
)


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


def _is_safe_zero_departed_box_row(service, sheet, row_number, layout, metric, raw_name, raw_region):
    if service._metric(metric) != "KUTU":
        return False
    if _unique_departed_identity(service, raw_name, raw_region) is None:
        return False

    values = service._read_metric_values(sheet, row_number, layout, "eski pasif temsilci")
    return values["total_actual"] == 0 and all(value == 0 for value in values["values"])


def install_production_result_stale_zero_guard():
    """Patch only representative-row collection; keep every downstream gate intact."""
    if getattr(ProductionResultImportService, "_stale_zero_guard_installed", False):
        return

    def guarded_read_sheet(self, sheet, metric):
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
                if _is_safe_zero_departed_box_row(
                    self,
                    sheet,
                    row_number,
                    layout,
                    metric,
                    raw_name,
                    raw_region,
                ):
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
        return rows

    ProductionResultImportService._read_sheet = guarded_read_sheet
    ProductionResultImportService._stale_zero_guard_installed = True
