"""Keep multi-month region results equal to the sum of finalized months.

Business rule: a multi-month period must never rebuild historical box values from
one price or from a mixed-period aggregate. Each month is finalized first with
that month's P2 > P1 > IMS source and period-aware unit price; rolling, quarter
and YTD views then add those monthly result values.
"""
from __future__ import annotations

from decimal import Decimal


_INSTALLED = False
_MISSING = object()


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
                bucket["gap_tl"] += _d(item.get("gap_tl"))

            unit_complete = bool(item.get("unit_complete")) and item.get("actual_unit") is not None
            bucket["unit_complete"] = bucket["unit_complete"] and unit_complete
            if unit_complete:
                bucket["actual_unit"] += _d(item.get("actual_unit"))
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


def _has_business_data(payload):
    """Return True only when a month is part of the real historical series."""
    return bool(
        _d(payload.get("target_tl"))
        or (payload.get("products") or [])
        or (payload.get("representatives") or [])
    )


def _merge_monthly_payloads(months, monthly_payloads):
    contributing = [payload for payload in monthly_payloads if _has_business_data(payload)]
    complete = bool(contributing) and all(
        bool(payload.get("complete")) and payload.get("actual_tl") is not None
        for payload in contributing
    )
    total_target = sum((_d(payload.get("target_tl")) for payload in contributing), Decimal("0"))
    total_actual = sum((_d(payload.get("actual_tl")) for payload in contributing), Decimal("0"))
    total_gap = sum((_d(payload.get("gap_tl")) for payload in contributing), Decimal("0"))

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
        "products": _merge_products(contributing),
        "representatives": _merge_representatives(contributing),
        "months": month_rows,
        "source_by_month": source_by_month,
    }


def _quarter_months(year, quarter):
    start = (int(quarter) - 1) * 3 + 1
    return [(int(year), month) for month in range(start, start + 3)]


def install_period_result_sum_guard():
    """Make every RegionPerformanceService consumer use finalized monthly sums."""
    global _INSTALLED
    if _INSTALLED:
        return

    from app.services.region_performance_service import RegionPerformanceService

    original_report = RegionPerformanceService.report
    original_aggregate = RegionPerformanceService.aggregate

    def finalized_month(self, period):
        normalized = (int(period[0]), int(period[1]))
        cache = getattr(self, "_period_result_sum_month_cache", None)
        if cache is None:
            return original_aggregate(self, [normalized])
        if normalized not in cache:
            cache[normalized] = original_aggregate(self, [normalized])
        return cache[normalized]

    def monthly_sum_aggregate(self, months):
        normalized = [(int(year), int(month)) for year, month in months]
        if not normalized:
            return original_aggregate(self, normalized)
        if len(normalized) == 1:
            return finalized_month(self, normalized[0])
        monthly_payloads = [finalized_month(self, period) for period in normalized]
        return _merge_monthly_payloads(normalized, monthly_payloads)

    def report(self):
        previous = getattr(self, "_period_result_sum_month_cache", _MISSING)
        self._period_result_sum_month_cache = {}
        try:
            result = original_report(self)
            periods = result.setdefault("periods", {})
            for quarter in range(1, 5):
                key = f"q{quarter}"
                months = _quarter_months(self.year, quarter)
                periods[key] = {
                    "key": key,
                    "label": key.upper(),
                    "month_count": 3,
                    **monthly_sum_aggregate(self, months),
                }
            if "yearly" in periods:
                periods["yearly"]["label"] = "YILLIK YTD"
            return result
        finally:
            if previous is _MISSING:
                delattr(self, "_period_result_sum_month_cache")
            else:
                self._period_result_sum_month_cache = previous

    RegionPerformanceService._pre_period_sum_report = original_report
    RegionPerformanceService._pre_period_sum_aggregate = original_aggregate
    RegionPerformanceService.report = report
    RegionPerformanceService.aggregate = monthly_sum_aggregate
    RegionPerformanceService._period_result_sum_guard_installed = True

    # The Türkiye cockpit consumes the region snapshot periods and performs no
    # source re-resolution. Expose the same fixed grouping vocabulary there so
    # every national panel is an aggregate of exactly the same region periods.
    try:
        from app.services.executive_market_cockpit_service import ExecutiveMarketCockpitService
        ExecutiveMarketCockpitService.PERIODS = (
            ("monthly", "Aylık"),
            ("q1", "Q1"),
            ("q2", "Q2"),
            ("q3", "Q3"),
            ("q4", "Q4"),
            ("half_year", "6 Aylık"),
            ("yearly", "YILLIK YTD"),
        )
        ExecutiveMarketCockpitService.PERIOD_LABELS = dict(ExecutiveMarketCockpitService.PERIODS)
    except ImportError:
        pass

    _INSTALLED = True