from flask import Blueprint, render_template
from flask_login import login_required

from app.services.dashboard_service import DashboardService

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")

@dashboard_bp.route("/")
@login_required
def index():
    """
    V3 Enterprise Thin Controller.
    Strictly acts as a bridge between the Orchestrator (DashboardService) and the View.
    Zero business logic, zero data generation, zero fallback mechanisms.
    """
    payload = DashboardService().run()
    
    return render_template("dashboard.html", payload=payload)
