"""Read-time TL overlay for cumulative partial IMS snapshots.

When a newer weekly IMS contains current representative/product TL data but
omits older NATIONAL/region subtotal sheets, keep direct official box metrics
from the last source that supplied them while replacing stale TL actuals (and
fully covered TL targets) with the newest cumulative IMS snapshot.
"""
from collections import defaultdict
from decimal import Decimal
from types import SimpleNamespace

from app.extensions import db
from app.models import IMSRawData, IMSSummary, Representative, Target
from app.query.dashboard_query import DashboardQuery
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
_ORIGINAL_MAP_REGIONS = None


def _region_key(value):
    value = str(value or "").strip()
    first = value.split()[0] if value else ""
    return first if first.isdigit() else value


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


def _latest_has_direct_region_subtotal(upload_id, region_key):
    if not upload_id:
        return False
    prefix = f"{str(region_key).strip()}%"
    return IMSRawData.query.filter(
        IMSRawData.upload_id == int(upload_id),
        IMSRawData.sheet_type.in_(("dashboard_balance_region", "dashboard_weekly_region")),
        IMSRawData.territory.like(prefix),
    ).first() is not None


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
    # If the newest workbook itself carries a direct region subtotal, that row
    # remains authoritative. The overlay exists only to bridge a newer compact
    # workbook that omitted the region subtotal layer entirely.
    if _latest_has_direct_region_subtotal(latest_id, self.region_key):
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
            target_tl = Decimal(str(overlay["target_tl"][pid]))
        if latest_id != actual_source and pid in overlay["actual_tl"]:
            actual_tl = Decimal(str(overlay["actual_tl"][pid]))
            complete = True
        result[product_id] = [target_tl, actual_tl, complete]
    return result


def _region_overlay_rows(year, month):
    """Return current TL target/actual totals at map-region grain in bounded reads."""
    latest_id = OfficialAggregateService.latest_upload_id(year, month)
    if not latest_id:
        return {}

    target_rows = db.session.query(
        Target.representative_id,
        Target.product_id,
        Target.tl_target,
        Representative.region,
        Representative.city,
    ).join(
        Representative, Representative.id == Target.representative_id
    ).filter(
        Target.year == year,
        Target.month == month,
        Representative.region.isnot(None),
    ).all()
    if not target_rows:
        return {}

    rep_region = {}
    region_targets = defaultdict(Decimal)
    region_target_keys = defaultdict(set)
    region_reps = defaultdict(set)
    city_by_region = {}
    for representative_id, product_id, tl_target, region, city in target_rows:
        rk = _region_key(region)
        if not rk:
            continue
        representative_id = int(representative_id)
        product_id = int(product_id)
        rep_region[representative_id] = rk
        region_reps[rk].add(representative_id)
        region_target_keys[rk].add((representative_id, product_id))
        region_targets[rk] += Decimal(str(tl_target or 0))
        if city and rk not in city_by_region:
            city_by_region[rk] = city

    summary_rows = db.session.query(
        IMSSummary.representative_id,
        IMSSummary.product_id,
        IMSSummary.tl,
    ).filter(
        IMSSummary.upload_id == latest_id,
        IMSSummary.year == year,
        IMSSummary.month == month,
        IMSSummary.representative_id.in_(list(rep_region)),
    ).all()

    region_actuals = defaultdict(Decimal)
    region_summary_keys = defaultdict(set)
    for representative_id, product_id, tl in summary_rows:
        representative_id = int(representative_id)
        rk = rep_region.get(representative_id)
        if not rk:
            continue
        key = (representative_id, int(product_id))
        region_summary_keys[rk].add(key)
        region_actuals[rk] += Decimal(str(tl or 0))

    result = {}
    for rk, target_keys in region_target_keys.items():
        result[rk] = {
            "upload_id": int(latest_id),
            "target_tl": region_targets[rk],
            "actual_tl": region_actuals[rk],
            "target_complete": bool(target_keys) and target_keys == region_summary_keys.get(rk, set()),
            "representative_count": len(region_reps[rk]),
            "city": city_by_region.get(rk),
        }
    return result


def _map_regions(self, filters=None):
    base = _ORIGINAL_MAP_REGIONS(self, filters)
    if not base or not filters or filters.year is None or filters.month is None:
        return base
    year, month = int(filters.year), int(filters.month)
    # P2/P1 region totals remain authoritative.
    if ProductionResultService.final_upload(year, month) is not None:
        return base

    overlays = _region_overlay_rows(year, month)
    if not overlays:
        return base
    target_source = OfficialAggregateService.latest_upload_id(year, month, TARGET_TYPE)
    actual_source = OfficialAggregateService.latest_upload_id(year, month, ACTUAL_TYPE)

    result = []
    for source_row in base:
        rk = _region_key(getattr(source_row, "region", None))
        overlay = overlays.get(rk)
        if not overlay or _latest_has_direct_region_subtotal(overlay["upload_id"], rk):
            result.append(source_row)
            continue

        target_tl = Decimal(str(getattr(source_row, "tl_target", 0) or 0))
        actual_tl = Decimal(str(getattr(source_row, "tl_actual", 0) or 0))
        if overlay["upload_id"] != target_source and overlay["target_complete"]:
            target_tl = overlay["target_tl"]
        if overlay["upload_id"] != actual_source:
            actual_tl = overlay["actual_tl"]

        result.append(SimpleNamespace(
            region=getattr(source_row, "region", rk),
            city=overlay.get("city") or getattr(source_row, "city", None),
            unit_target=getattr(source_row, "unit_target", Decimal("0")),
            unit_actual=getattr(source_row, "unit_actual", Decimal("0")),
            tl_target=target_tl,
            tl_actual=actual_tl,
            representative_count=overlay["representative_count"],
        ))
    return result


def install_partial_ims_tl_read_overlay():
    global _INSTALLED, _ORIGINAL_PRODUCT_TOTALS, _ORIGINAL_REGION_MONTH, _ORIGINAL_MAP_REGIONS
    if _INSTALLED:
        return
    _ORIGINAL_PRODUCT_TOTALS = OfficialAggregateService.product_totals
    _ORIGINAL_REGION_MONTH = RegionPerformanceService._official_ims_region_month
    _ORIGINAL_MAP_REGIONS = DashboardQuery.load_region_performance
    OfficialAggregateService.product_totals = staticmethod(_product_totals)
    RegionPerformanceService._official_ims_region_month = _region_month
    DashboardQuery.load_region_performance = _map_regions
    _INSTALLED = True
