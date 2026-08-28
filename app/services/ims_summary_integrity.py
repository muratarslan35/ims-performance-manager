"""Keep IMSSummary actuals aligned with the authoritative IMS period actuals.

This guard is deliberately narrow: it changes only ``ims_summary`` rows produced
by an IMS import. Targets, prime, dashboard formulas, production-result priority
and all other read models are untouched.

Weekly IMS workbooks are cumulative snapshots.  Their representative/product
actuals are persisted on ``Target.tl_realization`` / ``Target.unit_realization``
by the existing weekly-sales import contract.  ``rebuild_summary`` also creates
summary rows from generic FACT rows, and those FACT rows can contain several
report types for the same product.  If that generic aggregation survives, TL can
be zero while unit values are inflated by unrelated balance/brick measures.

After the normal workbook pipeline has finished, this guard copies the already
accepted weekly IMS actuals back onto only the current upload's summary rows.
Numeric zero is preserved as a real value.
"""
from __future__ import annotations

from app.extensions import db
from app.models import IMSSummary, Target


def synchronize_summary_from_targets(upload_id: int, year: int, month: int) -> int:
    """Synchronize current-upload summary actuals from persisted IMS target actuals.

    The caller is responsible for invoking this only when the workbook contains
    an authoritative cumulative weekly-sales source.  Limiting by ``upload_id``
    prevents any historical upload or other period from being modified.
    """
    summaries = IMSSummary.query.filter_by(
        upload_id=int(upload_id),
        year=int(year),
        month=int(month),
    ).all()
    if not summaries:
        return 0

    keys = {
        (int(item.representative_id), int(item.product_id))
        for item in summaries
        if item.representative_id is not None and item.product_id is not None
    }
    if not keys:
        return 0

    representative_ids = {key[0] for key in keys}
    product_ids = {key[1] for key in keys}
    targets = Target.query.filter(
        Target.year == int(year),
        Target.month == int(month),
        Target.representative_id.in_(representative_ids),
        Target.product_id.in_(product_ids),
    ).all()
    target_by_key = {
        (int(item.representative_id), int(item.product_id)): item
        for item in targets
    }

    changed = 0
    for summary in summaries:
        if summary.representative_id is None or summary.product_id is None:
            continue
        target = target_by_key.get((int(summary.representative_id), int(summary.product_id)))
        if target is None:
            continue

        actual_tl = float(target.tl_realization or 0.0)
        actual_unit = float(target.unit_realization or 0.0)
        target_tl = float(target.tl_target or 0.0)
        target_unit = float(target.unit_target or 0.0)
        realization_percent = round(actual_tl * 100.0 / target_tl, 2) if target_tl else 0.0

        before = (
            float(summary.tl or 0.0),
            float(summary.unit or 0.0),
            float(summary.target_tl or 0.0),
            float(summary.target_unit or 0.0),
            float(summary.realization_percent or 0.0),
        )
        after = (actual_tl, actual_unit, target_tl, target_unit, realization_percent)
        if before == after:
            continue

        summary.tl = actual_tl
        summary.unit = actual_unit
        summary.target_tl = target_tl
        summary.target_unit = target_unit
        summary.realization_percent = realization_percent
        changed += 1

    if changed:
        db.session.flush()
    return changed


def install_ims_summary_integrity() -> None:
    """Install one post-import summary invariant without changing other services."""
    from app.services.dynamic_import_contract import _profile_cache
    from app.services.ims_import_service import IMSImportService

    if getattr(IMSImportService, "_summary_integrity_installed", False):
        return

    original_process_workbook = IMSImportService.process_workbook

    def process_workbook_with_summary_integrity(self, year, month, week_number=None):
        result = original_process_workbook(self, year, month, week_number=week_number)

        # Replaying an older week must not publish period-scoped summary values.
        if not self._is_current_week_snapshot(year, month, week_number):
            return result

        # Only a workbook with an authoritative cumulative weekly-sales source
        # is eligible. This preserves legacy/monthly imports and genuine zeros.
        weekly_profile = _profile_cache(self).locate("weekly")
        if weekly_profile is None or self.upload is None:
            return result

        changed = synchronize_summary_from_targets(self.upload.id, year, month)
        self.statistics["summary_integrity_rows"] = changed
        return result

    IMSImportService.process_workbook = process_workbook_with_summary_integrity
    IMSImportService._summary_integrity_installed = True
