from flask import Blueprint, render_template
from flask_login import login_required

from app.cache.dashboard_cache import DashboardCache
from app.constants.dashboard_constants import DashboardConstants
from app.services.dashboard_service import DashboardService
from app.services.persistent_dashboard_snapshot_service import PersistentDashboardSnapshotService

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")

@dashboard_bp.route("/")
@login_required
def index():
    """Serve the ready dashboard snapshot shared by every Gunicorn worker.

    Business calculations remain inside DashboardService.  A durable snapshot
    created after IMS import lets login traffic read the same ready payload
    instead of making each worker rebuild the national dashboard independently.
    """
    service = DashboardService()
    payload = PersistentDashboardSnapshotService.get_active(service.year, service.month)
    if payload is None:
        # A source-identity change means an old per-process memory entry must not
        # win the fallback. Rebuild once from canonical services and atomically
        # publish it for all workers and following users.
        cache_key = DashboardConstants.CACHE_KEY_TEMPLATE.format(
            year=service.year,
            month=service.month,
            rep_id=service.rep_id,
        )
        DashboardCache().invalidate(cache_key)
        payload = service.run()
        PersistentDashboardSnapshotService.publish(service.year, service.month, payload)

    return render_template("dashboard.html", payload=payload)
