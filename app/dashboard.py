from flask import Blueprint, render_template
from flask_login import login_required

from app.services.period_service import PeriodService
from app.services.persistent_dashboard_snapshot_service import PersistentDashboardSnapshotService

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@dashboard_bp.route("/")
@login_required
def index():
    """Serve the durable dashboard read-model without calculating in HTTP."""
    active = PeriodService.get_active_period()
    payload = PersistentDashboardSnapshotService.get_active(
        active["year"], active["month"]
    )
    if payload is None:
        payload = {}
    return render_template("dashboard.html", payload=payload)
