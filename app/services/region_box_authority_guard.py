"""Keep region product box results on the same authority as displayed TL results.

From April 2026 onward an open IMS month uses the official region/product TL
subtotal and that product's period-effective unit price for both target and
actual boxes. This prevents mixed-authority rows where TL is below target while
box difference is shown as positive. P2/P1 production rows stay untouched.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from app.extensions import db
from app.models import IMSUpload, Representative, Target
from app.services.product_unit_price_service import ProductUnitPriceService
from app.services.production_result_service import ProductionResultService
from app.services.region_performance_service import RegionPerformanceService
from app.services.tl_box_calculation_service import TLBoxCalculationService

_INSTALLED = False


def _d(value):
    return Decimal(str(value or 0))


def _valid_price(value):
    try:
        return _d(value) > 0
    except (TypeError, ValueError, ArithmeticError):
        return False


def _authoritative_month_units(service, year, month):
    """Return product -> (target box, actual box, complete) for one month.

    Production months keep stored P2/P1 units. April+ IMS months derive both
    box values from the exact official region TL rows used by the same screen.
    Older months keep their existing official region unit authority.
    """
    if ProductionResultService.final_upload(year, month) is not None:
        return service._official_region_unit_month(year, month), True

    if TLBoxCalculationService.applies(year, month):
        official_tl = service._official_ims_region_month(year, month)
        if not official_tl:
            return {}, False
        prices = ProductUnitPriceService.price_map(official_tl.keys(), year, month)
        result = {}
        for product_id, values in official_tl.items():
            target_tl, actual_tl, complete = values
            price = prices.get(int(product_id))
            if not _valid_price(price):
                continue
            result[int(product_id)] = [
                TLBoxCalculationService.boxes_from_tl(target_tl, price),
                TLBoxCalculationService.boxes_from_tl(actual_tl, price) if complete else Decimal("0"),
                bool(complete),
            ]
        return result, bool(result)

    units = service._official_region_unit_month(year, month)
    return units, bool(units)


def install_region_box_authority_guard():
    """Install as the final region aggregate normalization layer."""
    global _INSTALLED
    if _INSTALLED:
        return

    original_aggregate = RegionPerformanceService.aggregate

    def guarded_aggregate(self, months):
        months = [(int(year), int(month)) for year, month in months]
        payload = original_aggregate(self, months)
        products = list(payload.get("products") or [])
        if not products:
            return payload

        product_ids = {int(item.get("product_id")) for item in products if item.get("product_id") is not None}
        desired = defaultdict(lambda: [Decimal("0"), Decimal("0"), True])
        covered = {product_id: True for product_id in product_ids}
        targeted_by_month = defaultdict(set)
        for row in self._target_rows(months):
            year, month, _rep_id, product_id = int(row[0]), int(row[1]), row[2], row[3]
            if product_id is not None:
                targeted_by_month[(year, month)].add(int(product_id))

        for year, month in months:
            month_units, month_has_authority = _authoritative_month_units(self, year, month)
            targeted = targeted_by_month.get((year, month), set())
            for product_id in product_ids:
                values = month_units.get(product_id)
                if values is not None:
                    desired[product_id][0] += _d(values[0])
                    desired[product_id][1] += _d(values[1])
                    desired[product_id][2] = desired[product_id][2] and bool(values[2])
                elif product_id in targeted and not month_has_authority:
                    # Preserve the pre-existing fallback rather than partially
                    # replacing a multi-month total with incomplete authority.
                    covered[product_id] = False
                elif product_id in targeted and month_has_authority:
                    # An authoritative source exists for the month but this
                    # product lacks a usable price/unit row. Fail closed.
                    covered[product_id] = False

        april_or_later = any(TLBoxCalculationService.applies(year, month) for year, month in months)
        for item in products:
            product_id = int(item.get("product_id"))
            if not covered.get(product_id):
                continue
            target_unit, actual_unit, complete = desired[product_id]
            item["target_unit"] = target_unit
            item["actual_unit"] = actual_unit if complete else None
            item["unit_complete"] = bool(complete)
            item["unit_difference"] = (actual_unit - target_unit) if complete else None
            if april_or_later:
                item["box_authority"] = "REGION_TL_PERIOD_PRICE"
        return payload

    RegionPerformanceService.aggregate = guarded_aggregate
    _INSTALLED = True


def audit_all_regions(year=None, month=None):
    """Read-only audit of the latest April+ month across every active region."""
    if year is None or month is None:
        latest = db.session.query(IMSUpload.year, IMSUpload.month).filter(
            IMSUpload.status == "COMPLETED"
        ).order_by(IMSUpload.year.desc(), IMSUpload.month.desc(), IMSUpload.week_number.desc(), IMSUpload.id.desc()).first()
        if latest is None:
            return {"year": None, "month": None, "regions": 0, "rows": 0, "failures": []}
        year, month = int(latest[0]), int(latest[1])
    year, month = int(year), int(month)
    if not TLBoxCalculationService.applies(year, month):
        return {"year": year, "month": month, "regions": 0, "rows": 0, "failures": []}

    region_rows = db.session.query(Representative.region).join(
        Target, Target.representative_id == Representative.id
    ).filter(
        Target.year == year,
        Target.month == month,
        Representative.region.isnot(None),
    ).distinct().all()
    region_keys = sorted({str(row[0]).strip() for row in region_rows if str(row[0] or "").strip()})

    failures = []
    checked = 0
    for region_key in region_keys:
        try:
            report = RegionPerformanceService(region_key, year, month).aggregate([(year, month)])
        except ValueError:
            continue
        for item in report.get("products", []):
            if item.get("actual_tl") is None or item.get("actual_unit") is None:
                continue
            checked += 1
            target_tl = _d(item.get("target_tl"))
            actual_tl = _d(item.get("actual_tl"))
            target_unit = _d(item.get("target_unit"))
            actual_unit = _d(item.get("actual_unit"))
            tl_cmp = (actual_tl > target_tl) - (actual_tl < target_tl)
            unit_cmp = (actual_unit > target_unit) - (actual_unit < target_unit)
            if tl_cmp != unit_cmp:
                failures.append({
                    "region": region_key,
                    "product": item.get("product_name"),
                    "target_tl": float(target_tl),
                    "actual_tl": float(actual_tl),
                    "target_unit": float(target_unit),
                    "actual_unit": float(actual_unit),
                })
    return {"year": year, "month": month, "regions": len(region_keys), "rows": checked, "failures": failures}
