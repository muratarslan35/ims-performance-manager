from copy import deepcopy

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.services.period_service import PeriodService
from app.services.persistent_region_snapshot_service import PersistentRegionSnapshotService
from app.services.region_performance_service import RegionPerformanceService
from app.services.region_market_service import RegionMarketService
from app.services.scoped_ai_insight_service import ScopedAIInsightService

regions_bp = Blueprint("regions", __name__, url_prefix="/regions")


_LEGACY_TEMPLATE_NUMERIC_KEYS = {
    "target_tl",
    "actual_tl",
    "gap_tl",
    "realization_percent",
    "target_unit",
    "actual_unit",
    "unit_difference",
    "percent",
}


def _legacy_template_safe_report(report):
    """Return a render-only copy safe for the legacy parent region template."""
    safe = deepcopy(report)

    def visit(value):
        if isinstance(value, dict):
            for key, child in list(value.items()):
                if key in _LEGACY_TEMPLATE_NUMERIC_KEYS and child is None:
                    value[key] = 0
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(safe)
    return safe


def _region_read_model(region_key, year, month):
    """Read the already-published region model before considering live queries.

    The normal production path is a durable snapshot created after IMS/production
    publication.  That snapshot already contains both the complete regional
    performance report and the market/competition model, so opening the manager
    page must not execute those expensive calculations again.  The live builder
    remains only as a compatibility fallback for a historical period that has no
    published snapshot yet.
    """
    snapshot = PersistentRegionSnapshotService.get_active(region_key, year, month)
    if snapshot is not None and snapshot.get("report") is not None:
        return snapshot, "snapshot"

    performance_service = RegionPerformanceService(region_key, year, month)
    report = performance_service.report()
    market_analysis = RegionMarketService(
        report["region_key"], performance_service.rep_ids, year, month
    ).build()
    return {"report": report, "market_analysis": market_analysis}, "compatibility"


@regions_bp.route("/<path:region_key>")
@login_required
def detail(region_key):
    active = PeriodService.get_active_period()
    year = request.args.get("year", active["year"], type=int)
    month = request.args.get("month", active["month"], type=int)
    try:
        read_model, region_data_source = _region_read_model(region_key, year, month)
        current_report = read_model["report"]
        market_analysis = read_model.get("market_analysis") or {}
    except ValueError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("dashboard.index"))

    # This enrichment is deterministic and runs only over the already-loaded
    # snapshot dictionaries. It performs no IMS/production/competition reads.
    ai_report = ScopedAIInsightService.build(
        scope_type="region",
        scope_name=current_report["region_name"],
        periods=current_report["periods"],
        market_analysis=market_analysis,
    )
    safe_report = _legacy_template_safe_report(current_report)
    return render_template(
        "region_performance_quarter.html",
        report=safe_report,
        legacy_report=safe_report,
        current_report=current_report,
        ai_report=ai_report,
        market_analysis=market_analysis,
        region_data_source=region_data_source,
    )
