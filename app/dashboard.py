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
    """Serve one durable dashboard read-model across all Gunicorn workers."""
    service = DashboardService()
    cache_key = DashboardConstants.CACHE_KEY_TEMPLATE.format(
        year=service.year,
        month=service.month,
        rep_id=service.rep_id,
    )

    def rebuild():
        # Source identity changed, therefore a process-local payload with the old
        # data must not win the fallback. Canonical calculations stay untouched.
        DashboardCache().invalidate(cache_key)
        return service.run()

    payload, _built = PersistentDashboardSnapshotService.get_or_build(
        service.year,
        service.month,
        rebuild,
    )
    return render_template("dashboard.html", payload=payload)
