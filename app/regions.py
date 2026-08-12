from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.services.period_service import PeriodService
from app.services.region_performance_service import RegionPerformanceService

regions_bp = Blueprint("regions", __name__, url_prefix="/regions")


@regions_bp.route("/<path:region_key>")
@login_required
def detail(region_key):
    active = PeriodService.get_active_period()
    year = request.args.get("year", active["year"], type=int)
    month = request.args.get("month", active["month"], type=int)
    try:
        report = RegionPerformanceService(region_key, year, month).report()
    except ValueError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("dashboard.index"))
    return render_template("region_performance.html", report=report)
