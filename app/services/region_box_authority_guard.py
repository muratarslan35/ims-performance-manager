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


def install_region_box_authority_guard():
    """Install as the final region aggregate normalization layer.

    The existing aggregate already contains correct legacy/production unit
    contributions. We therefore replace only the April+ open-IMS contribution
    by applying a delta: official region TL-derived boxes minus the previous
    representative-derived boxes for the same month/product. This preserves
    historical box authority and keeps the bounded report snapshot intact.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    original_aggregate = RegionPerformanceService.aggregate

    def guarded_aggregate(self, months):
        months = [(int(year), int(month)) for year, month in months]
        april_months = [
            (year, month) for year, month in months
            if TLBoxCalculationService.applies(year, month)
            and ProductionResultService.final_upload(year, month) is None
        ]
        payload = original_aggregate(self, months)
        products = list(payload.get("products") or [])
        if not products or not april_months:
            return payload

        product_ids = {int(item.get("product_id")) for item in products if item.get("product_id") is not None}
        old_units = defaultdict(lambda: [Decimal("0"), Decimal("0"), True])
        target_rows = self._target_rows(april_months)
        for year, month, rep_id, product_id, _target_tl, _stored_target_unit in target_rows:
            product_id = int(product_id)
            if product_id not in product_ids:
                continue
            effective = ProductionResultService.effective_product(year, month, rep_id, product_id)
            if str(effective.get("source") or "").startswith("PRODUCTION_"):
                continue
            old_units[(int(year), int(month), product_id)][0] += _d(effective.get("target_unit"))
            if not effective.get("complete") or effective.get("actual_unit") is None:
                old_units[(int(year), int(month), product_id)][2] = False
            else:
                old_units[(int(year), int(month), product_id)][1] += _d(effective.get("actual_unit"))

        target_delta = defaultdict(lambda: Decimal("0"))
        actual_delta = defaultdict(lambda: Decimal("0"))
        invalid_products = set()

        for year, month in april_months:
            official_tl = self._official_ims_region_month(year, month)
            if not official_tl:
                continue
            prices = ProductUnitPriceService.price_map(official_tl.keys(), year, month)
            for product_id, values in official_tl.items():
                product_id = int(product_id)
                if product_id not in product_ids:
                    continue
                price = prices.get(product_id)
                if not _valid_price(price):
                    invalid_products.add(product_id)
                    continue
                target_tl, actual_tl, complete = values
                old_target, old_actual, old_complete = old_units.get(
                    (year, month, product_id),
                    [Decimal("0"), Decimal("0"), False],
                )
                if not old_complete or not complete:
                    invalid_products.add(product_id)
                    continue
                correct_target = TLBoxCalculationService.boxes_from_tl(target_tl, price)
                correct_actual = TLBoxCalculationService.boxes_from_tl(actual_tl, price)
                target_delta[product_id] += correct_target - old_target
                actual_delta[product_id] += correct_actual - old_actual

        for item in products:
            product_id = int(item.get("product_id"))
            if product_id in invalid_products:
                continue
            if product_id not in target_delta and product_id not in actual_delta:
                continue
            target_unit = _d(item.get("target_unit")) + target_delta[product_id]
            actual_value = item.get("actual_unit")
            if actual_value is None:
                continue
            actual_unit = _d(actual_value) + actual_delta[product_id]
            item["target_unit"] = target_unit
            item["actual_unit"] = actual_unit
            item["unit_complete"] = True
            item["unit_difference"] = actual_unit - target_unit
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
