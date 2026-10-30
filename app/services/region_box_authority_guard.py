"""Keep region product box results on the same authority as displayed TL results.

From April 2026 onward an open IMS month uses the official region/product TL
subtotal and that product's period-effective unit price for both target and
actual boxes. This prevents mixed-authority rows where TL is below target while
box difference is shown as positive. P2/P1 production rows stay untouched.
"""
from __future__ import annotations

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

def _apply_direct_monthly_box_authority(service, payload, year, month):
    """Fill one open IMS month directly from official region TL + period price.

    Monthly region rows do not need a representative-unit baseline. When the
    IMS workbook has authoritative region/product TL totals, derive both target
    and actual boxes from the same period-effective unit price even if legacy
    representative actual_unit values are absent.
    """
    products = list((payload or {}).get("products") or [])
    if not products:
        return payload

    official_tl = service._official_ims_region_month(int(year), int(month))
    if not official_tl:
        return payload

    product_ids = {
        int(item.get("product_id"))
        for item in products
        if item.get("product_id") is not None
    }
    prices = ProductUnitPriceService.price_map(product_ids, int(year), int(month))

    for item in products:
        product_id = item.get("product_id")
        if product_id is None:
            continue
        product_id = int(product_id)
        values = official_tl.get(product_id)
        price = prices.get(product_id)
        if values is None or not _valid_price(price):
            continue
        target_tl, actual_tl, complete = values
        if not complete or actual_tl is None:
            continue

        target_unit = TLBoxCalculationService.boxes_from_tl(target_tl, price)
        actual_unit = TLBoxCalculationService.boxes_from_tl(actual_tl, price)
        item["target_unit"] = target_unit
        item["actual_unit"] = actual_unit
        item["unit_complete"] = True
        item["unit_difference"] = actual_unit - target_unit
        item["box_authority"] = "REGION_TL_PERIOD_PRICE"

    return payload


def install_region_box_authority_guard():
    """Install as the final region aggregate normalization layer.

    The base aggregate owns official monthly region units. This final monthly
    check also normalizes cached/legacy rows by exact value, never just by the
    direction of realization. Closed production months remain untouched.
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

        # A monthly row is a single-period view, so its box values can be
        # derived directly from the authoritative region TL subtotal and the
        # period-effective unit price. Do not require legacy representative
        # actual_unit completeness for this calculation.
        if len(months) == 1 and len(april_months) == 1:
            year, month = april_months[0]
            return _apply_direct_monthly_box_authority(
                self, payload, year, month
            )

        # Multi-period boxes are already built from each month's official
        # region units by the base aggregate. Do not apply a representative
        # delta a second time.
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
            service = RegionPerformanceService(region_key, year, month)
            report = service.aggregate([(year, month)])
            official = service._official_ims_region_month(year, month)
            prices = ProductUnitPriceService.price_map(official.keys(), year, month)
        except ValueError as exc:
            failures.append({"region": region_key, "reason": str(exc)})
            continue
        if {int(item["product_id"]) for item in report.get("products", [])} != set(official):
            failures.append({"region": region_key, "reason": "official_product_coverage_mismatch"})
        for item in report.get("products", []):
            if item.get("actual_tl") is None or item.get("actual_unit") is None:
                failures.append({"region": region_key, "product_id": item.get("product_id"), "reason": "incomplete_official_result"})
                continue
            checked += 1
            target_tl = _d(item.get("target_tl"))
            actual_tl = _d(item.get("actual_tl"))
            target_unit = _d(item.get("target_unit"))
            actual_unit = _d(item.get("actual_unit"))
            product_id = int(item["product_id"])
            values = official.get(product_id)
            price = prices.get(product_id)
            if values is None or not _valid_price(price):
                failures.append({"region": region_key, "product_id": product_id, "reason": "missing_official_source_or_price"})
                continue
            expected_target = TLBoxCalculationService.boxes_from_tl(values[0], price)
            expected_actual = TLBoxCalculationService.boxes_from_tl(values[1], price)
            if target_unit != expected_target or actual_unit != expected_actual:
                failures.append({
                    "region": region_key,
                    "product": item.get("product_name"),
                    "target_tl": float(target_tl),
                    "actual_tl": float(actual_tl),
                    "target_unit": float(target_unit),
                    "actual_unit": float(actual_unit),
                })
    return {"year": year, "month": month, "regions": len(region_keys), "rows": checked, "failures": failures}
