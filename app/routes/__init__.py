from flask import Blueprint
from flask import redirect
from flask import render_template
from flask import url_for
from flask import request

from flask_login import current_user
from flask_login import login_required
from app.services.dashboard_service import DashboardService
from app.services.market_analysis_service import MarketAnalysisService
from app.models import Representative
from app.services.quarter_entitlement_service import QuarterEntitlementService


main_bp = Blueprint(
    "main",
    __name__
)


@main_bp.route("/")
@login_required
def home():
    return render_template(
        "dashboard.html",
        user=current_user
    )


@main_bp.route("/dashboard")
@login_required
def dashboard():
    return redirect(
        url_for("dashboard.index")
    )

@main_bp.route("/market-analysis")
@login_required
def market_analysis():
    dashboard_service = DashboardService()
    payload = dashboard_service.run()
    payload["competition_analysis"] = MarketAnalysisService(
        dashboard_service.year,
        dashboard_service.month,
    ).build()
    return render_template("market_analysis.html", payload=payload)


@main_bp.route("/prime")
@login_required
def prime():
    return render_template(
        "prime.html",
        user=current_user
    )


@main_bp.route("/reports")
@login_required
def reports():
    return render_template(
        "reports.html",
        user=current_user
    )


@main_bp.route("/quarter")
@login_required
def quarter():
    representatives = Representative.query.filter_by(active=True).order_by(Representative.rep_name.asc()).all()
    year = request.args.get("year", type=int) or 2026
    quarter = request.args.get("quarter", type=int) or 2
    representative_id = request.args.get("representative_id", type=int)
    report = None
    selected_representative = None
    if representative_id:
        selected_representative = Representative.query.get_or_404(representative_id)
        report = QuarterEntitlementService(representative_id, year, quarter).report()
    return render_template(
        "quarter.html",
        representatives=representatives,
        selected_representative=selected_representative,
        report=report,
        selected_year=year,
        selected_quarter=quarter,
    )


@main_bp.route("/recovery")
@login_required
def recovery():
    return redirect(
        url_for("simulation.index")
    )


@main_bp.route("/settings")
@login_required
def settings():
    return redirect(
        url_for("settings.index")
    )
