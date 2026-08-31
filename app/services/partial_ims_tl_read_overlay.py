"""Read-time TL overlay for cumulative partial IMS snapshots.

When a newer weekly IMS contains current representative/product TL data but
omits the older NATIONAL/region subtotal sheets, keep direct official box
metrics from the last source that supplied them while replacing stale TL
actuals (and fully covered TL targets) with the newest cumulative IMS snapshot.
"""
from collections import defaultdict

from app.models import IMSSummary, Target
from app.services.official_aggregate_service import (
    ACTUAL_TYPE,
    TARGET_TYPE,
    OfficialAggregateService,
)
from app.services.production_result_service import ProductionResultService
from app.services.region_performance_service import RegionPerformanceService

_INSTALLED = False
_ORIGINAL_PRODUCT_TOTALS = None
_ORIGINAL_REGION_MONTH = None


def _tl_overlay(year, month, representative_ids=None):
    upload_id = OfficialAggregateService.latest_upload_id(year, month)
    if not upload_id:
        return None

    summaries = IMSSummary.query.filter_by(
        upload_id=upload_id, year=year, month=month
    )
    targets = Target.query.filter_by(year=year, month=month)
    if representative_ids is not None:
        rep_ids = [int(value) for value in representative_ids]
        if not rep_ids:
            return None
        summaries = summaries.filter(IMSSummary.representative_id.in_(rep_ids))
        targets = targets.filter(Target.representative_id.in_(rep_ids))

    summary_rows = summaries.all()
    target_rows = targets.all()
    if not summary_rows:
        return None

    actual_tl = defaultdict(float)
    target_tl = defaultdict(float)
    summary_keys = set()
    target_keys = set()
    for row in summary_rows:
        key = (int(row.representative_id), int(row.product_id))
        summary_keys.add(key)
        actual_tl[int(row.product_id)] += float(row.tl or 0)
    for row in target_rows:
        key = (int(row.representative_id), int(row.product_id))
        target_keys.add(key)
        target_tl[int(row.product_id)] += float(row.tl_target or 0)

    return {
        "upload_id": int(upload_id),
        "actual_tl": dict(actual_tl),
        "target_tl": dict(target_tl),
        "target_complete": bool(target_keys) and target_keys == summary_keys,
    }


def _product_totals(year, month, territory):
    base = _ORIGINAL_PRODUCT_TOTALS(year, month, territory)
    if not base or str(territory) != "NATIONAL":
        return base

    overlay = _tl_overlay(year, month)
    if not overlay:
        return base
    target_source = OfficialAggregateService.latest_upload_id(year, month, TARGET_TYPE)
    actual_source = OfficialAggregateService.latest_upload_id(year, month, ACTUAL_TYPE)
    latest_id = overlay["upload_id"]
    if latest_id == target_source and latest_id == actual_source:
        return base

    result = []
    for source_row in base:
        row = dict(source_row)
        product_id = int(row["product_id"])
        if (
            latest_id != target_source
            and overlay["target_complete"]
            and product_id in overlay["target_tl"]
        ):
            row["target_tl"] = float(overlay["target_tl"][product_id])
        if latest_id != actual_source and product_id in overlay["actual_tl"]:
            row["actual_tl"] = float(overlay["actual_tl"][product_id])
        # target_unit / actual_unit intentionally remain on their last direct
        # official company-box source. Competition boxes are never substituted.
        result.append(row)
    return result


def _region_month(self, year, month):
    base = _ORIGINAL_REGION_MONTH(self, year, month)
    if not base:
        return base
    # P2/P1 stays authoritative exactly as before.
    if ProductionResultService.final_upload(year, month) is not None:
        return base

    overlay = _tl_overlay(year, month, self.rep_ids)
    if not overlay:
        return base
    target_source = OfficialAggregateService.latest_upload_id(year, month, TARGET_TYPE)
    actual_source = OfficialAggregateService.latest_upload_id(year, month, ACTUAL_TYPE)
    latest_id = overlay["upload_id"]
    if latest_id == target_source and latest_id == actual_source:
        return base

    result = {}
    for product_id, values in base.items():
        target_tl, actual_tl, complete = values
        pid = int(product_id)
        if (
            latest_id != target_source
            and overlay["target_complete"]
            and pid in overlay["target_tl"]
        ):
            target_tl = overlay["target_tl"][pid]
        if latest_id != actual_source and pid in overlay["actual_tl"]:
            actual_tl = overlay["actual_tl"][pid]
            complete = True
        result[product_id] = [target_tl, actual_tl, complete]
    return result


def install_partial_ims_tl_read_overlay():
    global _INSTALLED, _ORIGINAL_PRODUCT_TOTALS, _ORIGINAL_REGION_MONTH
    if _INSTALLED:
        return
    _ORIGINAL_PRODUCT_TOTALS = OfficialAggregateService.product_totals
    _ORIGINAL_REGION_MONTH = RegionPerformanceService._official_ims_region_month
    OfficialAggregateService.product_totals = staticmethod(_product_totals)
    RegionPerformanceService._official_ims_region_month = _region_month
    _INSTALLED = True
