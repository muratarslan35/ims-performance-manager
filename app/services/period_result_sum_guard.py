"""Keep 3/6/12-month region results equal to the sum of finalized months.

Business rule: a multi-month period must never rebuild historical box values from
one price or from a mixed-period aggregate. Each month is finalized first with
that month's P2 > P1 > IMS source and period-aware unit price; 3/6/12-month
views then add those monthly result values.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal


_INSTALLED = False


def _d(value):
    return Decimal(str(value or 0))


def _percent(actual, target):
    target = _d(target)
    return (_d(actual) * Decimal("100") / target) if target else Decimal("0")


def _merge_products(monthly_payloads):
    rows = {}
    for payload in monthly_payloads:
        for item in payload.get("products") or []:
            product_id = int(item["product_id"])
            bucket = rows.setdefault(product_id, {
                "product_id": product_id,
                "product_name": item.get("product_name") or f"Ürün {product_id}",
                "target_tl": Decimal("0"),
                "actual_tl": Decimal("0"),
                "gap_tl": Decimal("0"),
                "target_unit": Decimal("0"),
                "actual_unit": Decimal("0"),
                "unit_difference": Decimal("0"),
                "complete": True,
                "unit_complete": True,
                "quota_exit": False,
                "quota_exit_months": [],
            })
            bucket["target_tl"] += _d(item.get("target_tl"))
            bucket["target_unit"] += _d(item.get("target_unit"))
            bucket["quota_exit"] = bucket["quota_exit"] or bool(item.get("quota_exit"))
            for label in item.get("quota_exit_months") or []:
                if label not in bucket["quota_exit_months"]:
                    bucket["quota_exit_months"].append(label)

            complete = bool(item.get("complete")) and item.get("actual_tl") is not None
            bucket["complete"] = bucket["complete"] and complete
            if complete:
                bucket["actual_tl"] += _d(item.get("actual_tl"))
                # Sum the already-finalized monthly TL difference instead of
                # reconstructing a historical result after months are mixed.
                bucket["gap_tl"] += _d(item.get("gap_tl"))

            unit_complete = bool(item.get("unit_complete")) and item.get("actual_unit") is not None
            bucket["unit_complete"] = bucket["unit_complete"] and unit_complete
            if unit_complete:
                bucket["actual_unit"] += _d(item.get("actual_unit"))
                # This is the critical rule: preserve each month's own price,
                # rounding and source decision, then add the monthly box result.
                bucket["unit_difference"] += _d(item.get("unit_difference"))

    result = []
    for bucket in rows.values():
        if bucket["complete"]:
            bucket["realization_percent"] = _percent(bucket["actual_tl"], bucket["target_tl"])
        else:
            bucket["actual_tl"] = None
            bucket["gap_tl"] = None
            bucket["realization_percent"] = None
        if not bucket["unit_complete"]:
            bucket["actual_unit"] = None
            bucket["unit_difference"] = None
        result.append(bucket)
    result.sort(key=lambda row: (-(_d(row.get("actual_tl"))), row.get("product_name") or ""))
    return result


def _merge_representatives(monthly_payloads):
    rows = {}
    for payload in monthly_payloads:
        for item in payload.get("representatives") or []:
            representative_id = int(item["representative_id"])
            bucket = rows.setdefault(representative_id, {
                "representative_id": representative_id,
                "representative_name": item.get("representative_name"),
                "city": item.get("city"),
                "active": bool(item.get("active")),
                "is_vacant": bool(item.get("is_vacant")),
                "target_tl": Decimal("0"),
                "actual_tl": Decimal("0"),
                "gap_tl": Decimal("0"),
                "complete": True,
            })
            bucket["target_tl"] += _d(item.get("target_tl"))
            complete = bool(item.get("complete")) and item.get("actual_tl") is not None
            bucket["complete"] = bucket["complete"] and complete
            if complete:
                bucket["actual_tl"] += _d(item.get("actual_tl"))
                bucket["gap_tl"] += _d(item.get("gap_tl"))

    result = []
    for bucket in rows.values():
        if bucket["complete"]:
            bucket["realization_percent"] = _percent(bucket["actual_tl"], bucket["target_tl"])
        else:
            bucket["actual_tl"] = None
            bucket["gap_tl"] = None
            bucket["realization_percent"] = None
        result.append(bucket)
    result.sort(key=lambda row: (-(_d(row.get("realization_percent"))), -(_d(row.get("actual_tl")))))
    return result


def _merge_monthly_payloads(months, monthly_payloads):
    complete = bool(monthly_payloads) and all(
        bool(payload.get("complete")) and payload.get("actual_tl") is not None
        for payload in monthly_payloads
    )
    total_target = sum((_d(payload.get("target_tl")) for payload in monthly_payloads), Decimal("0"))
    total_actual = sum((_d(payload.get("actual_tl")) for payload in monthly_payloads), Decimal("0"))
    total_gap = sum((_d(payload.get("gap_tl")) for payload in monthly_payloads), Decimal("0"))

    month_rows = []
    source_by_month = {}
    for payload in monthly_payloads:
        month_rows.extend(payload.get("months") or [])
        source_by_month.update(payload.get("source_by_month") or {})

    return {
        "target_tl": total_target,
        "actual_tl": total_actual if complete else None,
        "realization_percent": _percent(total_actual, total_target) if complete else None,
        "gap_tl": total_gap if complete else None,
        "complete": complete,
        "products": _merge_products(monthly_payloads),
        "representatives": _merge_representatives(monthly_payloads),
        "months": month_rows,
        "source_by_month": source_by_month,
    }


def install_period_result_sum_guard():
    """Make every RegionPerformanceService consumer use finalized monthly sums."""
    global _INSTALLED
    if _INSTALLED:
        return

    from app.services.region_performance_service import RegionPerformanceService

    original_aggregate = RegionPerformanceService.aggregate

    def monthly_sum_aggregate(self, months):
        normalized = [(int(year), int(month)) for year, month in months]
        if len(normalized) <= 1:
            return original_aggregate(self, normalized)

        # Intentionally call the fully-installed one-month read path. It already
        # contains source precedence, price history, approved box rounding and
        # all production/IMS read repairs. Multi-month periods only add results.
        monthly_payloads = [original_aggregate(self, [period]) for period in normalized]
        return _merge_monthly_payloads(normalized, monthly_payloads)

    RegionPerformanceService._pre_period_sum_aggregate = original_aggregate
    RegionPerformanceService.aggregate = monthly_sum_aggregate
    RegionPerformanceService._period_result_sum_guard_installed = True
    _INSTALLED = True
