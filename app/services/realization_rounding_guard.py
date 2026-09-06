"""Apply the canonical realization rounding rule to live read models.

This guard is presentation/read-only. It deliberately leaves stored target/actual
values, production source precedence and prime calculations untouched.
"""
from __future__ import annotations

from functools import wraps

from app.services.realization_rounding import realization_percent


_INSTALLED = False


def normalize_realization_payload(value):
    """Recalculate present TL realization fields from their exact target/actual pair.

    A missing realization (``None``) is a business signal meaning the period has
    no authoritative IMS/production result yet. Never turn that signal into zero.
    """
    if isinstance(value, list):
        for item in value:
            normalize_realization_payload(item)
        return value
    if isinstance(value, tuple):
        for item in value:
            normalize_realization_payload(item)
        return value
    if not isinstance(value, dict):
        return value

    for child in value.values():
        normalize_realization_payload(child)

    target = value.get("target_tl")
    actual = value.get("actual_tl")
    if target is not None and actual is not None:
        if value.get("realization_percent") is not None:
            value["realization_percent"] = realization_percent(actual, target)
        if value.get("tl_realization_percent") is not None:
            value["tl_realization_percent"] = realization_percent(actual, target)
        # Annual chart rows use `percent` for the same TL realization metric.
        # `None` means no authoritative result; preserve it exactly.
        if value.get("percent") is not None and ("month" in value or "has_data" in value):
            value["percent"] = realization_percent(actual, target)
    return value


def _wrap_output(owner, method_name):
    descriptor = owner.__dict__.get(method_name)
    if descriptor is None:
        return
    if isinstance(descriptor, classmethod):
        original = descriptor.__func__

        @wraps(original)
        def wrapper(cls, *args, **kwargs):
            return normalize_realization_payload(original(cls, *args, **kwargs))

        setattr(owner, method_name, classmethod(wrapper))
        return
    if isinstance(descriptor, staticmethod):
        original = descriptor.__func__

        @wraps(original)
        def wrapper(*args, **kwargs):
            return normalize_realization_payload(original(*args, **kwargs))

        setattr(owner, method_name, staticmethod(wrapper))
        return

    original = descriptor

    @wraps(original)
    def wrapper(self, *args, **kwargs):
        return normalize_realization_payload(original(self, *args, **kwargs))

    setattr(owner, method_name, wrapper)


def install_realization_rounding_guard():
    global _INSTALLED
    if _INSTALLED:
        return

    # Primary region and representative period calculators.
    from app.services.region_performance_service import RegionPerformanceService
    from app.services.representative_period_snapshot_service import RepresentativePeriodSnapshotService
    RegionPerformanceService.percent = staticmethod(realization_percent)
    RepresentativePeriodSnapshotService._percent = staticmethod(realization_percent)

    # Annual charts and AI read models.
    from app.services.annual_realization_service import AnnualRealizationService
    from app.services.scoped_ai_insight_service import ScopedAIInsightService
    ScopedAIInsightService._percent = staticmethod(realization_percent)
    _wrap_output(AnnualRealizationService, "build")
    _wrap_output(AnnualRealizationService, "build_representative")

    # Dashboard query payloads. Prime/quarter engines are intentionally excluded.
    from app.query.dashboard_query import DashboardQuery
    for name in (
        "load_top_representatives", "load_city_performance", "load_region_performance",
        "load_history", "load_period_performance", "load_product_performance",
        "load_national_dashboard_metrics",
    ):
        _wrap_output(DashboardQuery, name)

    # Market / executive / representative analysis read models.
    from app.services.executive_market_cockpit_service import ExecutiveMarketCockpitService
    from app.services.region_market_service import RegionMarketService
    from app.services.representative_market_service import RepresentativeMarketService
    for owner, name in (
        (ExecutiveMarketCockpitService, "build"),
        (RegionMarketService, "build"),
        (RepresentativeMarketService, "build"),
    ):
        _wrap_output(owner, name)

    _INSTALLED = True
