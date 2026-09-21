from flask import Blueprint, render_template
from flask_login import login_required

from app.cache.dashboard_cache import DashboardCache
from app.constants.dashboard_constants import DashboardConstants
from app.services.dashboard_service import DashboardService
from app.services.persistent_dashboard_snapshot_service import PersistentDashboardSnapshotService
from app.services.ims_publication_service import IMSPublicationService

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


def _ensure_ytd_product_rankings(payload, service):
    """One-time compatibility upgrade for older dashboard read models."""
    upgraded = dict(payload or {})
    changed = False
    existing = (payload or {}).get("ytd_product_rankings")
    ytd_current = (
        isinstance(existing, dict)
        and int(existing.get("rank_trend_version") or 0) >= 1
        and int(existing.get("source_version") or 0) >= 2
    )
    if not ytd_current:
        rows = service.query_layer.load_ytd_product_rankings(
            service.year, service.month
        )
        rankings = service._ytd_product_rankings(
            rows, service.year, service.month
        )
        upgraded["ytd_product_rankings"] = service._ytd_rankings_with_previous_trend(
            rankings
        )
        changed = True

    # The first realization-based release could still serve a durable payload
    # created while this leaderboard was TL-ranked. Rebuild only this field
    # once from the existing period data; no IMS replay is required.
    if int(upgraded.get("top_representative_ranking_version") or 0) < 2:
        rows = service.query_layer.load_top_representatives(
            filters=service.query_filters, limit=None
        )
        mapped = service.mapper.map_top_reps(rows)
        upgraded.update(service.formatter.format_top_reps(mapped))
        upgraded["top_representative_ranking_version"] = 2
        changed = True

    if changed:
        PersistentDashboardSnapshotService.publish(
            service.year, service.month, upgraded
        )
    return upgraded


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

    payload = None
    if IMSPublicationService.pending_job(service.year, service.month) is not None:
        payload = PersistentDashboardSnapshotService.get_stable(service.year, service.month)
    if payload is None:
        payload, _built = PersistentDashboardSnapshotService.get_or_build(
            service.year,
            service.month,
            rebuild,
        )
    payload = _ensure_ytd_product_rankings(payload, service)
    return render_template("dashboard.html", payload=payload)
