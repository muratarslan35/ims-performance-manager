from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.services.period_service import PeriodService
from app.services.region_performance_service import RegionPerformanceService
from app.services.region_market_service import RegionMarketService
from app.services.scoped_ai_insight_service import ScopedAIInsightService

regions_bp = Blueprint("regions", __name__, url_prefix="/regions")


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
        "region_performance.html", report=report, ai_report=ai_report,
        market_analysis=market_analysis,
    )
