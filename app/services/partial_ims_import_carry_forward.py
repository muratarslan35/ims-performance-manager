"""Overlay representative IMS actuals when a weekly workbook is partial.

A compact regional workbook may contain the current cumulative representative/product
TL snapshot while omitting box, competition and brick-spread layers. Such a workbook
must update the representative's current IMS position without adding the previous
week a second time.

For March TL-only partial files, missing current box totals are derived from the same
representative/product effective price in the previous full March IMS. If that basis
is unavailable, the March target TL/unit ratio is used. Current product list prices
are deliberately not used for March because of the Feb->Mar price transition. From
April onward, the configured current unit price may be used.

Competition, market share, brick spread, prime and P2>P1>IMS precedence remain
untouched.
"""
from __future__ import annotations

from sqlalchemy import desc, func

from app.extensions import db
from app.models import IMSFact, IMSSummary, IMSUpload, Product, Target


def _safe_price(tl_value, unit_value):
    tl_value = float(tl_value or 0.0)
    unit_value = float(unit_value or 0.0)
    return tl_value / unit_value if tl_value > 0.0 and unit_value > 0.0 else 0.0


def derive_missing_unit_delta(
    *,
    month,
    incremental_tl,
    incremental_unit,
    previous_unit,
    previous_tl,
    target_unit=0.0,
    target_tl=0.0,
    configured_unit_price=0.0,
):
    """Derive a missing current box total using period-appropriate price basis.

    The historical parameter names are retained for compatibility, but the incoming
    TL/unit values are the current cumulative snapshot, not an additive delta.
    """
    current_unit = float(incremental_unit or 0.0)
    current_tl = float(incremental_tl or 0.0)
    if current_unit != 0.0 or current_tl == 0.0:
        return current_unit, "source"

    month = int(month)
    previous_effective_price = _safe_price(previous_tl, previous_unit)
    target_effective_price = _safe_price(target_tl, target_unit)
    configured_unit_price = float(configured_unit_price or 0.0)

    if month == 3:
        candidates = (
            (previous_effective_price, "previous_full_march_ims"),
            (target_effective_price, "march_target_ratio"),
        )
    elif month > 3:
        candidates = (
            (configured_unit_price, "configured_current_unit_price"),
            (previous_effective_price, "previous_full_ims"),
            (target_effective_price, "target_ratio"),
        )
    else:
        candidates = (
            (previous_effective_price, "previous_full_ims"),
            (target_effective_price, "target_ratio"),
        )

    for price, source in candidates:
        if price > 0.0:
            return float(round(current_tl / price)), source
    return 0.0, "unavailable"


def overlay_snapshot_actuals(previous_unit, previous_tl, current_unit, current_tl):
    """Use the current partial IMS snapshot without double-counting prior actuals."""
    del previous_unit, previous_tl
    return float(current_unit or 0.0), float(current_tl or 0.0)


def _actual_snapshot(year: int, month: int):
    return {
        (int(row.representative_id), int(row.product_id)): (
            float(row.unit_realization or 0.0),
            float(row.tl_realization or 0.0),
        )
        for row in Target.query.filter_by(year=int(year), month=int(month)).all()
    }


def _is_partial_compact_upload(importer) -> bool:
    upload = getattr(importer, "upload", None)
    if upload is None:
        return False
    stats = getattr(importer, "statistics", {}) or {}
    if int(upload.sheet_count or 0) > 2:
        return False
    if int(stats.get("processed_sheets", 0) or 0) > 1:
        return False
    if int(stats.get("official_brick_spread_present", 0) or 0) != 0:
        return False

    unit_total, tl_total = (
        db.session.query(
            func.coalesce(func.sum(func.abs(IMSSummary.unit)), 0.0),
            func.coalesce(func.sum(func.abs(IMSSummary.tl)), 0.0),
        )
        .filter(IMSSummary.upload_id == int(upload.id))
        .one()
    )
    return float(unit_total or 0.0) == 0.0 and float(tl_total or 0.0) > 0.0


def _previous_full_brick_sales_baseline(upload: IMSUpload):
    previous = (
        IMSUpload.query.filter(
            IMSUpload.status == "COMPLETED",
            IMSUpload.year == int(upload.year),
            IMSUpload.month == int(upload.month),
            IMSUpload.week_number.isnot(None),
            IMSUpload.week_number < int(upload.week_number or 0),
            IMSUpload.sheet_count > 2,
        )
        .order_by(desc(IMSUpload.week_number), desc(IMSUpload.id))
        .first()
    )
    if previous is None:
        return None, {}

    rows = (
        db.session.query(
            IMSFact.representative_id,
            IMSFact.product_id,
            func.sum(IMSFact.unit),
            func.sum(IMSFact.tl),
        )
        .filter(
            IMSFact.upload_id == int(previous.id),
            IMSFact.report_type == "brick_sales",
            IMSFact.representative_id.isnot(None),
        )
        .group_by(IMSFact.representative_id, IMSFact.product_id)
        .all()
    )
    baseline = {
        (int(rep_id), int(product_id)): (float(unit or 0.0), float(tl or 0.0))
        for rep_id, product_id, unit, tl in rows
    }
    return previous, baseline


def _restore_summary_from_source_facts(upload: IMSUpload) -> int:
    """Restore mutable summary values from immutable current-upload brick_sales facts."""
    rows = (
        db.session.query(
            IMSFact.representative_id,
            IMSFact.product_id,
            func.sum(IMSFact.unit),
            func.sum(IMSFact.tl),
        )
        .filter(
            IMSFact.upload_id == int(upload.id),
            IMSFact.report_type == "brick_sales",
            IMSFact.representative_id.isnot(None),
        )
        .group_by(IMSFact.representative_id, IMSFact.product_id)
        .all()
    )
    source = {
        (int(rep_id), int(product_id)): (float(unit or 0.0), float(tl or 0.0))
        for rep_id, product_id, unit, tl in rows
    }
    restored = 0
    for summary in IMSSummary.query.filter_by(upload_id=int(upload.id)).all():
        if summary.representative_id is None or summary.product_id is None:
            continue
        key = (int(summary.representative_id), int(summary.product_id))
        if key not in source:
            continue
        summary.unit, summary.tl = source[key]
        restored += 1
    if restored:
        db.session.flush()
    return restored


def _apply_overlay_actuals(upload_id: int, year: int, month: int, baseline: dict) -> tuple[int, dict]:
    summaries = IMSSummary.query.filter_by(
        upload_id=int(upload_id), year=int(year), month=int(month)
    ).all()
    targets = {
        (int(row.representative_id), int(row.product_id)): row
        for row in Target.query.filter_by(year=int(year), month=int(month)).all()
    }
    products = {int(row.id): row for row in Product.query.all()}

    changed = 0
    unit_sources = {}
    for summary in summaries:
        if summary.representative_id is None or summary.product_id is None:
            continue
        key = (int(summary.representative_id), int(summary.product_id))
        previous_unit, previous_tl = baseline.get(key, (0.0, 0.0))
        target = targets.get(key)
        product = products.get(int(summary.product_id))
        current_tl = float(summary.tl or 0.0)
        current_unit = float(summary.unit or 0.0)

        derived_unit, unit_source = derive_missing_unit_delta(
            month=month,
            incremental_tl=current_tl,
            incremental_unit=current_unit,
            previous_unit=previous_unit,
            previous_tl=previous_tl,
            target_unit=float(target.unit_target or 0.0) if target is not None else 0.0,
            target_tl=float(target.tl_target or 0.0) if target is not None else 0.0,
            configured_unit_price=float(product.unit_price or 0.0) if product is not None else 0.0,
        )
        unit_sources[unit_source] = unit_sources.get(unit_source, 0) + 1
        overlay_unit, overlay_tl = overlay_snapshot_actuals(
            previous_unit, previous_tl, derived_unit, current_tl
        )

        if target is not None:
            target.unit_realization = overlay_unit
            target.tl_realization = overlay_tl
            target_tl = float(target.tl_target or 0.0)
            target.realization_percent = round(overlay_tl * 100.0 / target_tl, 2) if target_tl else 0.0
            summary.target_unit = float(target.unit_target or 0.0)
            summary.target_tl = target_tl
        else:
            target_tl = float(summary.target_tl or 0.0)

        summary.unit = overlay_unit
        summary.tl = overlay_tl
        summary.realization_percent = round(overlay_tl * 100.0 / target_tl, 2) if target_tl else 0.0
        changed += 1

    if changed:
        db.session.flush()
    return changed, unit_sources


def repair_existing_partial_upload(upload_id: int) -> dict:
    """Rebuild one published partial upload as a current cumulative overlay snapshot."""
    upload = db.session.get(IMSUpload, int(upload_id))
    if upload is None:
        raise ValueError(f"IMS upload {upload_id} bulunamadı")
    if upload.status != "COMPLETED" or upload.week_number is None:
        raise ValueError("Yalnızca tamamlanmış haftalık IMS upload onarılabilir")
    if int(upload.sheet_count or 0) > 2:
        raise ValueError("Upload compact/partial görünmüyor; onarım reddedildi")

    previous, baseline = _previous_full_brick_sales_baseline(upload)
    if previous is None or not baseline:
        raise ValueError("Önceki tam brick_sales baseline bulunamadı")

    restored = _restore_summary_from_source_facts(upload)
    source_totals = (
        db.session.query(
            func.coalesce(func.sum(IMSSummary.unit), 0.0),
            func.coalesce(func.sum(IMSSummary.tl), 0.0),
        )
        .filter(IMSSummary.upload_id == int(upload.id))
        .one()
    )
    if float(source_totals[1] or 0.0) <= 0.0:
        raise ValueError("Upload kaynak snapshot TL verisi taşımıyor")

    rows, unit_sources = _apply_overlay_actuals(upload.id, upload.year, upload.month, baseline)
    combined = (
        db.session.query(
            func.coalesce(func.sum(IMSSummary.unit), 0.0),
            func.coalesce(func.sum(IMSSummary.tl), 0.0),
        )
        .filter(IMSSummary.upload_id == int(upload.id))
        .one()
    )
    return {
        "upload_id": int(upload.id),
        "baseline_upload_id": int(previous.id),
        "restored_rows": int(restored),
        "rows": int(rows),
        "source_tl": float(source_totals[1] or 0.0),
        "overlay_unit": float(combined[0] or 0.0),
        "overlay_tl": float(combined[1] or 0.0),
        "unit_sources": unit_sources,
    }


def install_partial_ims_carry_forward() -> None:
    from app.services.ims_import_service import IMSImportService

    if getattr(IMSImportService, "_partial_ims_carry_forward_installed", False):
        return

    original_process = IMSImportService.process_workbook

    def process_with_partial_carry_forward(self, year, month, week_number=None):
        prior_target_snapshot = _actual_snapshot(year, month)
        result = original_process(self, year, month, week_number=week_number)

        if not self._is_current_week_snapshot(year, month, week_number):
            return result
        if not _is_partial_compact_upload(self):
            self.statistics["partial_ims_carry_forward"] = 0
            return result

        previous, full_baseline = _previous_full_brick_sales_baseline(self.upload)
        baseline = full_baseline or prior_target_snapshot
        if not baseline or not any(unit != 0.0 or tl != 0.0 for unit, tl in baseline.values()):
            self.statistics["partial_ims_carry_forward"] = 0
            return result

        changed, unit_sources = _apply_overlay_actuals(self.upload.id, year, month, baseline)
        self.statistics["partial_ims_carry_forward"] = 1
        self.statistics["partial_ims_carry_forward_mode"] = "cumulative_overlay"
        self.statistics["partial_ims_carry_forward_rows"] = changed
        self.statistics["partial_ims_baseline_rows"] = len(baseline)
        self.statistics["partial_ims_baseline_upload_id"] = int(previous.id) if previous is not None else None
        self.statistics["partial_ims_unit_sources"] = unit_sources
        return result

    IMSImportService.process_workbook = process_with_partial_carry_forward
    IMSImportService._partial_ims_carry_forward_installed = True
