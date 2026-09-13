"""Keep multi-month region results equal to the sum of finalized months.

Business rule: a multi-month period must never rebuild historical box values from
one price or from a mixed-period aggregate. Each month is finalized first with
that month's P2 > P1 > IMS source and period-aware unit price; rolling, quarter
and YTD views then add those monthly result values.

Persisted H1 read models are normalized at read time from already-published Q1
and Q2 payloads. This keeps the fixed January-June contract available without
rebuilding region or representative snapshot generations.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from app.services.realization_rounding import realization_percent


_INSTALLED = False
_MISSING = object()


def _d(value):
    return Decimal(str(value or 0))


def _percent(actual, target):
    return realization_percent(actual, target)


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


def _empty_period():
    return {
        "target_tl": Decimal("0"),
        "actual_tl": None,
        "realization_percent": None,
        "gap_tl": None,
        "complete": False,
        "products": [],
        "representatives": [],
        "months": [],
        "source_by_month": {},
    }


def _compose_region_half_year_snapshot(snapshot):
    """Return the same persisted region payload with H1 derived from Q1 + Q2."""
    if not isinstance(snapshot, dict):
        return snapshot
    report = snapshot.get("report")
    periods = report.get("periods") if isinstance(report, dict) else None
    if not isinstance(periods, dict):
        return snapshot

    q1 = periods.get("q1") or {}
    q2 = periods.get("q2") or {}
    if not (q1.get("months") or q2.get("months")):
        return snapshot

    merged = _merge_monthly_payloads([], [q1, q2])
    result = dict(snapshot)
    normalized_report = dict(report)
    normalized_periods = dict(periods)
    normalized_periods["half_year"] = {
        "key": "half_year",
        "label": "6 Aylık · Ocak–Haziran",
        "month_count": len(merged.get("months") or []),
        **merged,
    }
    normalized_report["periods"] = normalized_periods
    result["report"] = normalized_report
    return result


def _representative_product_id(row):
    product = (row or {}).get("product") or {}
    value = product.get("id") if isinstance(product, dict) else getattr(product, "id", None)
    if value is None:
        value = (row or {}).get("product_id")
    return int(value) if value is not None else None


def _representative_product_name(row, product_id):
    product = (row or {}).get("product") or {}
    if isinstance(product, dict):
        name = product.get("product_name")
    else:
        name = getattr(product, "product_name", None)
    return name or (row or {}).get("product_name") or f"Ürün {product_id}"


def _merge_representative_product_rows(periods):
    rows = {}
    source_rank = {"IMS": 0, "PRODUCTION_1": 1, "PRODUCTION_2": 2}
    for period in periods:
        for item in period.get("products") or []:
            product_id = _representative_product_id(item)
            if product_id is None:
                continue
            if product_id not in rows:
                rows[product_id] = {
                    "product": deepcopy(item.get("product")),
                    "target_tl": 0.0,
                    "actual_tl": 0.0,
                    "target_unit": 0.0,
                    "actual_unit": 0.0,
                    "remaining_tl": 0.0,
                    "source": item.get("source") or "IMS",
                }
            bucket = rows[product_id]
            for key in ("target_tl", "actual_tl", "target_unit", "actual_unit", "remaining_tl"):
                bucket[key] += float(item.get(key) or 0)
            candidate = item.get("source") or "IMS"
            if source_rank.get(candidate, 0) > source_rank.get(bucket.get("source"), 0):
                bucket["source"] = candidate

    result = []
    for product_id, bucket in rows.items():
        if not bucket.get("product"):
            bucket["product"] = {
                "id": product_id,
                "product_name": _representative_product_name({}, product_id),
            }
        bucket["percent"] = (
            realization_percent(bucket["actual_tl"], bucket["target_tl"])
            if bucket["target_tl"] else 0
        )
        result.append(bucket)
    result.sort(
        key=lambda row: (
            int((row.get("product") or {}).get("display_order", 999))
            if isinstance(row.get("product"), dict) else 999,
            _representative_product_name(row, _representative_product_id(row)),
        )
    )
    return result


def _merge_representative_totals(periods):
    totals = {
        "target_tl": 0.0,
        "actual_tl": 0.0,
        "target_unit": 0.0,
        "actual_unit": 0.0,
        "remaining_tl": 0.0,
    }
    for period in periods:
        source = period.get("totals") or {}
        for key in totals:
            totals[key] += float(source.get(key) or 0)
    totals = {key: round(value, 2) for key, value in totals.items()}
    totals["percent"] = (
        realization_percent(totals["actual_tl"], totals["target_tl"])
        if totals["target_tl"] else 0
    )
    return totals


def _merge_representative_market(markets):
    available = [payload for payload in markets if isinstance(payload, dict)]
    if not available:
        return {}
    if len(available) == 1:
        return deepcopy(available[0])

    result = deepcopy(available[-1])
    product_rows = {}
    for payload in available:
        for row in payload.get("rows") or []:
            product_id = _representative_product_id(row)
            if product_id is None:
                continue
            if product_id not in product_rows:
                product_rows[product_id] = deepcopy(row)
                continue
            bucket = product_rows[product_id]
            for key in ("actual_unit", "market_unit", "competitor_unit", "target_unit"):
                bucket[key] = float(bucket.get(key) or 0) + float(row.get(key) or 0)
            rivals = {}
            for rival in bucket.get("rivals") or []:
                name = str(rival.get("name") or "").strip()
                if name:
                    rivals[name] = rivals.get(name, 0.0) + float(rival.get("unit") or 0)
            for rival in row.get("rivals") or []:
                name = str(rival.get("name") or "").strip()
                if name:
                    rivals[name] = rivals.get(name, 0.0) + float(rival.get("unit") or 0)
            bucket["rivals"] = [
                {"name": name, "unit": round(unit, 2)}
                for name, unit in sorted(rivals.items(), key=lambda item: -item[1])
            ]

    rows = list(product_rows.values())
    for row in rows:
        actual = float(row.get("actual_unit") or 0)
        market = float(row.get("market_unit") or 0)
        competitor = float(row.get("competitor_unit") or 0)
        target = float(row.get("target_unit") or 0)
        row["share_percent"] = round(actual * 100.0 / market, 1) if market else 0.0
        row["gap_unit"] = round(competitor - actual, 2)
        row["realization_percent"] = realization_percent(actual, target) if target else 0
        row["attention"] = (
            "critical" if competitor > actual * 1.5 and competitor > 0
            else "warning" if competitor > actual
            else "strong"
        )
    rows.sort(
        key=lambda row: (
            int((row.get("product") or {}).get("display_order", 999))
            if isinstance(row.get("product"), dict) else 999,
            _representative_product_name(row, _representative_product_id(row)),
        )
    )
    result["rows"] = rows
    result["chart_rows"] = [
        {
            "product_name": _representative_product_name(row, _representative_product_id(row)),
            "actual_unit": row.get("actual_unit") or 0,
            "competitor_unit": row.get("competitor_unit") or 0,
        }
        for row in rows
    ]
    total_actual = sum(float(row.get("actual_unit") or 0) for row in rows)
    total_market = sum(float(row.get("market_unit") or 0) for row in rows)
    result["totals"] = {
        "actual_unit": round(total_actual, 2),
        "market_unit": round(total_market, 2),
        "competitor_unit": round(max(total_market - total_actual, 0.0), 2),
        "share_percent": round(total_actual * 100.0 / total_market, 1) if total_market else 0.0,
    }
    result["period_months"] = [
        item
        for payload in available
        for item in (payload.get("period_months") or [])
    ]
    return result


def _representative_ai_period(products, totals, month_count):
    return {
        "key": "half_year",
        "label": "6 Aylık · Ocak–Haziran",
        "month_count": int(month_count),
        "target_tl": totals["target_tl"],
        "actual_tl": totals["actual_tl"],
        "realization_percent": totals["percent"],
        "gap_tl": totals["target_tl"] - totals["actual_tl"],
        "complete": True,
        "products": [
            {
                "product_id": _representative_product_id(row),
                "product_name": _representative_product_name(
                    row, _representative_product_id(row)
                ),
                "target_tl": row.get("target_tl") or 0,
                "actual_tl": row.get("actual_tl") or 0,
                "realization_percent": row.get("percent") or 0,
                "gap_tl": float(row.get("target_tl") or 0) - float(row.get("actual_tl") or 0),
                "complete": True,
            }
            for row in products
            if _representative_product_id(row) is not None
        ],
        "representatives": [],
    }


def _compose_representative_half_year_workspace(workspace):
    """Derive persisted representative H1 from Q1 + Q2 without a snapshot rebuild."""
    if not isinstance(workspace, dict):
        return workspace
    snapshots = workspace.get("snapshots")
    if not isinstance(snapshots, dict):
        return workspace

    q1 = snapshots.get("q1") or {}
    q2 = snapshots.get("q2") or {}
    months = list(q1.get("months") or []) + list(q2.get("months") or [])
    if not months:
        return workspace

    contributing = [
        period for period in (q1, q2)
        if (period.get("products") or period.get("totals") or period.get("months"))
    ]
    if not contributing:
        return workspace

    products = _merge_representative_product_rows(contributing)
    totals = _merge_representative_totals(contributing)
    market = _merge_representative_market([
        period.get("market_analysis") or {} for period in contributing
    ])
    terminal = q2 if q2.get("months") else q1
    source_ai = terminal.get("ai_report") or q1.get("ai_report") or {}

    try:
        from app.services.scoped_ai_insight_service import ScopedAIInsightService
        ai_report = ScopedAIInsightService.build(
            scope_type="representative",
            scope_name=source_ai.get("scope_name") or "Temsilci",
            periods={
                "half_year": _representative_ai_period(
                    products, totals, len(months)
                )
            },
            market_analysis=market,
            competitive_intelligence=source_ai.get("competitive_intelligence") or {},
        )
    except (ImportError, RuntimeError):
        ai_report = deepcopy(source_ai)
        ai_report["periods"] = {
            "half_year": _representative_ai_period(products, totals, len(months))
        }

    half_year = {
        "key": "half_year",
        "label": "6 Aylık · Ocak–Haziran",
        "months": months,
        "products": products,
        "totals": totals,
        "assignments": deepcopy(terminal.get("assignments") or []),
        "market_analysis": market,
        "has_production_result": any(
            bool(period.get("has_production_result")) for period in contributing
        ),
        "result_source_label": (
            "Dönemsel P2 > P1 > IMS toplamı"
            if len(months) > 1
            else terminal.get("result_source_label") or "Seçili IMS dönemine kadar"
        ),
        "ai_report": ai_report,
    }

    result = dict(workspace)
    normalized_snapshots = dict(snapshots)
    normalized_snapshots["half_year"] = half_year
    result["snapshots"] = normalized_snapshots
    return result


def _install_persisted_h1_read_guard():
    """Normalize old ACTIVE snapshots in memory only; never rebuild or write them."""
    from app.services.persistent_region_snapshot_service import PersistentRegionSnapshotService
    from app.services.persistent_representative_snapshot_service import (
        PersistentRepresentativeSnapshotService,
    )

    if not getattr(PersistentRegionSnapshotService, "_h1_read_guard_installed", False):
        original_region_get_active = PersistentRegionSnapshotService.get_active
        original_region_get_active_all = PersistentRegionSnapshotService.get_active_all

        def region_get_active(cls, region_key, year, month):
            return _compose_region_half_year_snapshot(
                original_region_get_active(region_key, year, month)
            )

        def region_get_active_all(cls, year, month):
            payloads = original_region_get_active_all(year, month)
            return {
                key: _compose_region_half_year_snapshot(payload)
                for key, payload in (payloads or {}).items()
            }

        PersistentRegionSnapshotService.get_active = classmethod(region_get_active)
        PersistentRegionSnapshotService.get_active_all = classmethod(region_get_active_all)
        PersistentRegionSnapshotService._h1_read_guard_installed = True

    if not getattr(PersistentRepresentativeSnapshotService, "_h1_read_guard_installed", False):
        original_representative_get_active = PersistentRepresentativeSnapshotService.get_active

        def representative_get_active(cls, representative_id, year, month):
            return _compose_representative_half_year_workspace(
                original_representative_get_active(representative_id, year, month)
            )

        PersistentRepresentativeSnapshotService.get_active = classmethod(
            representative_get_active
        )
        PersistentRepresentativeSnapshotService._h1_read_guard_installed = True


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
            return _empty_period()
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
            yearly_month_rows = (periods.get("yearly") or {}).get("months") or []
            available_months = [
                int(row.get("month")) for row in yearly_month_rows
                if int(row.get("year") or self.year) == int(self.year) and row.get("month")
            ]
            cutoff_month = max(available_months, default=int(self.month))
            for quarter in range(1, 5):
                key = f"q{quarter}"
                months = [
                    period for period in _quarter_months(self.year, quarter)
                    if period[1] <= cutoff_month
                ]
                periods[key] = {
                    "key": key,
                    "label": key.upper(),
                    "month_count": len(months),
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

    try:
        from app.services.executive_market_cockpit_service import ExecutiveMarketCockpitService
        ExecutiveMarketCockpitService.PERIODS = (
            ("monthly", "Aylık"), ("q1", "Q1"), ("q2", "Q2"), ("q3", "Q3"), ("q4", "Q4"),
            ("half_year", "6 Aylık · Ocak–Haziran"), ("yearly", "YILLIK YTD"),
        )
        ExecutiveMarketCockpitService.PERIOD_LABELS = dict(ExecutiveMarketCockpitService.PERIODS)
    except ImportError:
        pass

    _install_persisted_h1_read_guard()
    _INSTALLED = True
