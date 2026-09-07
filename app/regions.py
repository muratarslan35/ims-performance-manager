from copy import deepcopy

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.services.period_service import PeriodService
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
    """Return a render-only copy safe for the legacy parent region template.

    The quarter template is the visible/current UI and already renders incomplete
    metrics as an em dash. Its parent template is still evaluated by Jinja before
    JavaScript hides the legacy period panels; old ``format(None)`` expressions
    therefore used to raise a 500 before the current UI could render. This helper
    changes only that hidden parent copy and never mutates business/report values.
    """
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


@regions_bp.route("/<path:region_key>")
@login_required
def detail(region_key):
    active = PeriodService.get_active_period()
    year = request.args.get("year", active["year"], type=int)
    month = request.args.get("month", active["month"], type=int)
    try:
        performance_service = RegionPerformanceService(region_key, year, month)
        report = performance_service.report()
    except ValueError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("dashboard.index"))
    ai_report = ScopedAIInsightService.build(
        scope_type="region", scope_name=report["region_name"], periods=report["periods"]
    )
    market_analysis = RegionMarketService(
        report["region_key"], performance_service.rep_ids, year, month
    ).build()
    return render_template(
        "region_performance_quarter.html",
        report=report,
        legacy_report=_legacy_template_safe_report(report),
        ai_report=ai_report,
        market_analysis=market_analysis,
    )
