"""Carry forward representative IMS actuals when a weekly workbook is partial.

A compact regional workbook may contain only incremental representative/product
TL exits and omit the usual box, competition and brick-spread layers.  Such a
workbook must not zero the representative's already-published IMS position.

This adapter is intentionally narrow:
- only current-week compact/partial uploads are eligible;
- current TL/unit values are treated as increments over the pre-import period
  actuals;
- missing unit data therefore preserves the previous unit realization;
- targets and IMSSummary actuals are updated together;
- competition, market-share, brick-spread, prime and P2>P1>IMS precedence are
  untouched.

A separate repair helper exists for an already-published partial upload.  It uses
the previous completed week's authoritative ``brick_sales`` facts as its baseline
so it never mixes competition/realization fact streams into representative sales.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import desc, func

from app.extensions import db
from app.models import IMSFact, IMSSummary, IMSUpload, Target


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

    totals = (
        db.session.query(
            func.coalesce(func.sum(func.abs(IMSSummary.unit)), 0.0),
            func.coalesce(func.sum(func.abs(IMSSummary.tl)), 0.0),
        )
        .filter(IMSSummary.upload_id == int(upload.id))
        .one()
    )
    unit_total, tl_total = float(totals[0] or 0.0), float(totals[1] or 0.0)
    return unit_total == 0.0 and tl_total > 0.0


def _apply_incremental_actuals(upload_id: int, year: int, month: int, baseline: dict) -> int:
    summaries = IMSSummary.query.filter_by(
        upload_id=int(upload_id), year=int(year), month=int(month)
    ).all()
    targets = {
        (int(row.representative_id), int(row.product_id)): row
        for row in Target.query.filter_by(year=int(year), month=int(month)).all()
    }

    changed = 0
    for summary in summaries:
        if summary.representative_id is None or summary.product_id is None:
            continue
        key = (int(summary.representative_id), int(summary.product_id))
        previous_unit, previous_tl = baseline.get(key, (0.0, 0.0))
        incremental_unit = float(summary.unit or 0.0)
        incremental_tl = float(summary.tl or 0.0)
        combined_unit = previous_unit + incremental_unit
        combined_tl = previous_tl + incremental_tl

        target = targets.get(key)
        if target is not None:
            target.unit_realization = combined_unit
            target.tl_realization = combined_tl
            target_tl = float(target.tl_target or 0.0)
            target.realization_percent = round(combined_tl * 100.0 / target_tl, 2) if target_tl else 0.0
            summary.target_unit = float(target.unit_target or 0.0)
            summary.target_tl = target_tl
        else:
            target_tl = float(summary.target_tl or 0.0)

        summary.unit = combined_unit
        summary.tl = combined_tl
        summary.realization_percent = round(combined_tl * 100.0 / target_tl, 2) if target_tl else 0.0
        changed += 1

    if changed:
        db.session.flush()
    return changed


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


def repair_existing_partial_upload(upload_id: int) -> dict:
    """Repair one already-published compact partial upload from prior full sales facts."""
    upload = IMSUpload.query.get(int(upload_id))
    if upload is None:
        raise ValueError(f"IMS upload {upload_id} bulunamadı")
    if upload.status != "COMPLETED" or upload.week_number is None:
        raise ValueError("Yalnızca tamamlanmış haftalık IMS upload onarılabilir")
    if int(upload.sheet_count or 0) > 2:
        raise ValueError("Upload compact/partial görünmüyor; onarım reddedildi")

    unit_total, tl_total = (
        db.session.query(
            func.coalesce(func.sum(func.abs(IMSSummary.unit)), 0.0),
            func.coalesce(func.sum(func.abs(IMSSummary.tl)), 0.0),
        )
        .filter(IMSSummary.upload_id == int(upload.id))
        .one()
    )
    if float(unit_total or 0.0) != 0.0 or float(tl_total or 0.0) <= 0.0:
        raise ValueError("Upload beklenen TL-only partial imzasını taşımıyor")

    previous, baseline = _previous_full_brick_sales_baseline(upload)
    if previous is None or not baseline:
        raise ValueError("Önceki tam brick_sales baseline bulunamadı")

    delta_tl = float(tl_total or 0.0)
    rows = _apply_incremental_actuals(upload.id, upload.year, upload.month, baseline)
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
        "rows": int(rows),
        "incremental_tl": delta_tl,
        "combined_unit": float(combined[0] or 0.0),
        "combined_tl": float(combined[1] or 0.0),
    }


def install_partial_ims_carry_forward() -> None:
    from app.services.ims_import_service import IMSImportService

    if getattr(IMSImportService, "_partial_ims_carry_forward_installed", False):
        return

    original_process = IMSImportService.process_workbook

    def process_with_partial_carry_forward(self, year, month, week_number=None):
        baseline = _actual_snapshot(year, month)
        result = original_process(self, year, month, week_number=week_number)

        if not self._is_current_week_snapshot(year, month, week_number):
            return result
        if not _is_partial_compact_upload(self):
            self.statistics["partial_ims_carry_forward"] = 0
            return result
        if not baseline or not any(unit != 0.0 or tl != 0.0 for unit, tl in baseline.values()):
            self.statistics["partial_ims_carry_forward"] = 0
            return result

        changed = _apply_incremental_actuals(self.upload.id, year, month, baseline)
        self.statistics["partial_ims_carry_forward"] = 1
        self.statistics["partial_ims_carry_forward_rows"] = changed
        self.statistics["partial_ims_baseline_rows"] = len(baseline)
        return result

    IMSImportService.process_workbook = process_with_partial_carry_forward
    IMSImportService._partial_ims_carry_forward_installed = True
