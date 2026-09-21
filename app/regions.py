from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.services.period_service import PeriodService
from app.services.persistent_dashboard_snapshot_service import PersistentDashboardSnapshotService
from app.services.persistent_region_snapshot_service import PersistentRegionSnapshotService

regions_bp = Blueprint("regions", __name__, url_prefix="/regions")


def _assigned_region_manager(report):
    """Resolve the active manager account assigned to this region."""
    from app.models import User
    from app.region_manager import RegionManagerScope, region_code

    target_code = region_code(
        report.get("region_key") or report.get("region_name") or ""
    )
    if target_code:
        scopes = RegionManagerScope.query.filter_by(manager_type="region").all()
        for scope in scopes:
            if region_code(scope.region_code) == target_code and scope.user and scope.user.active:
                return scope.user

    manager_name = str(report.get("manager") or "").strip().casefold()
    if manager_name and manager_name != "-":
        matches = [
            user for user in User.query.filter(User.active.is_(True)).all()
            if str(user.full_name or "").strip().casefold() == manager_name
        ]
        if len(matches) == 1:
            return matches[0]
    return None


def _region_read_model(region_key, year, month, *, source_upload_id=None):
    """Return only an already-published region read model.

    Interactive region pages never fall back to RegionPerformanceService or
    RegionMarketService. Missing read models are handled as a publication/warmup
    state instead of running heavy calculations inside a web request.
    """
    snapshot = None
    if source_upload_id:
        snapshot = PersistentRegionSnapshotService.get_active_for_visible_upload(
            region_key, year, month, source_upload_id
        )
        if snapshot is None:
            snapshot = PersistentRegionSnapshotService.get_active(
                region_key, year, month
            )
    else:
        snapshot = PersistentRegionSnapshotService.get_active(
            region_key, year, month
        )
    return (snapshot, "read-model") if snapshot is not None else (None, "unavailable")


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
        if read_model is None:
            flash(
                "Bölge görünümü hazırlanıyor. Hazır veri yayınlandığında tekrar deneyin.",
                "info",
            )
            return redirect(url_for("dashboard.index"))

        # Old region generations are finalized once from the already-published
        # representative/dashboard read models. After this one-time upgrade the
        # request path is a single region payload read plus template rendering.
        read_model_version = int(read_model.get("read_model_version") or 0)
        if read_model_version < 3:
            enrichment = PersistentRegionSnapshotService.enrich_for_period(
                year, month
            )
            if enrichment.get("status") in {"ENRICHED", "REUSED"}:
                read_model, region_data_source = _region_read_model(
                    region_key, year, month, source_upload_id=visible_upload_id
                )
        elif read_model_version < PersistentRegionSnapshotService.READ_MODEL_VERSION:
            enrichment = PersistentRegionSnapshotService.upgrade_national_realizations_for_period(
                year, month
            )
            if enrichment.get("status") == "ENRICHED":
                read_model, region_data_source = _region_read_model(
                    region_key, year, month, source_upload_id=visible_upload_id
                )

        if (
            read_model is None
            or int(read_model.get("read_model_version") or 0) < PersistentRegionSnapshotService.READ_MODEL_VERSION
            or not isinstance(read_model.get("ai_report"), dict)
        ):
            flash(
                "Bölge görünümü hazırlanıyor. Temsilci verileri tamamlandığında otomatik olarak hazır olacaktır.",
                "info",
            )
            return redirect(url_for("dashboard.index"))

        current_report = read_model["report"]
        market_analysis = read_model.get("market_analysis") or {}
        ai_report = read_model.get("ai_report") or {}
        region_manager = _assigned_region_manager(current_report)
    except ValueError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("dashboard.index"))

    return render_template(
        "region_performance_quarter.html",
        report=current_report,
        legacy_report=current_report,
        current_report=current_report,
        ai_report=ai_report,
        market_analysis=market_analysis,
        region_data_source=region_data_source,
        region_manager=region_manager,
        quarter_mode=True,
    )
