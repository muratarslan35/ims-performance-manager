from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.services.period_service import PeriodService
from app.services.persistent_region_snapshot_service import PersistentRegionSnapshotService
from app.services.region_performance_service import RegionPerformanceService
from app.services.region_market_service import RegionMarketService
from app.services.scoped_ai_insight_service import ScopedAIInsightService

regions_bp = Blueprint("regions", __name__, url_prefix="/regions")


def _region_read_model(region_key, year, month, *, source_upload_id=None):
    """Read the already-published region model before considering live queries.

    For the active period, PeriodService has already resolved the visible IMS
    upload and publication gate. Reuse that identity so a map click performs one
    bounded snapshot query instead of repeating IMS/pending-job checks. Historical
    periods keep the canonical visibility resolver. Live calculation remains only
    a compatibility fallback when no durable payload is available.
    """
    snapshot = None
    if source_upload_id:
        snapshot = PersistentRegionSnapshotService.get_active_for_visible_upload(
            region_key, year, month, source_upload_id
        )
        # A production-result snapshot may still be BUILDING. Preserve the
        # canonical previous-generation visibility rule during that short window.
        if snapshot is None:
            snapshot = PersistentRegionSnapshotService.get_active(region_key, year, month)
    else:
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
    visible_upload_id = (
        active.get("upload_id")
        if int(year) == int(active["year"]) and int(month) == int(active["month"])
        else None
    )
    try:
        read_model, region_data_source = _region_read_model(
            region_key, year, month, source_upload_id=visible_upload_id
        )
        current_report = read_model["report"]
        market_analysis = read_model.get("market_analysis") or {}
    except ValueError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("dashboard.index"))

    # This enrichment is deterministic and runs only over the already-loaded
    # snapshot dictionaries. It performs no IMS/production/competition reads.
    ai_report = read_model.get("ai_report") or ScopedAIInsightService.build(
        scope_type="region",
        scope_name=current_report["region_name"],
        periods=current_report["periods"],
        market_analysis=market_analysis,
    )

    # The quarter template suppresses the legacy duplicate period tables in its
    # parent, so the durable report can be reused directly without a full nested
    # deepcopy/traversal on every request.
    return render_template(
        "region_performance_quarter.html",
        report=current_report,
        legacy_report=current_report,
        current_report=current_report,
        ai_report=ai_report,
        market_analysis=market_analysis,
        region_data_source=region_data_source,
        quarter_mode=True,
    )
