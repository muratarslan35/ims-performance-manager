from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.services.period_service import PeriodService
from app.services.historical_region_read_model_service import HistoricalRegionReadModelService
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


def _compatibility_region_read_model(region_key, year, month):
    """Read an already-built historical model; never calculate on a page request."""
    payload = HistoricalRegionReadModelService.get_active(region_key, year, month)
    return (payload, "compatibility" if payload is not None else "unavailable")


def _region_read_model(region_key, year, month, *, source_upload_id=None):
    """Prefer exact snapshots, retaining the legacy historical fallback.

    The active IMS period remains snapshot-gated. Historical periods are
    different: some months were created before snapshot persistence existed,
    and a late production upload may temporarily have no exact ACTIVE snapshot.
    In those cases only a previously published compatibility model is eligible;
    HTTP requests never run the authoritative calculation chain.
    """
    if source_upload_id:
        snapshot = PersistentRegionSnapshotService.get_active_for_visible_upload(
            region_key, year, month, source_upload_id
        )
        if snapshot is None:
            snapshot = PersistentRegionSnapshotService.get_active(
                region_key, year, month
            )
        return (
            (snapshot, "read-model")
            if snapshot is not None
            else (None, "unavailable")
        )

    ims_id, _production_id = PersistentRegionSnapshotService.source_identity(
        year, month
    )
    exact = (
        PersistentRegionSnapshotService.get_active_for_visible_upload(
            region_key, year, month, ims_id
        )
        if ims_id
        else None
    )
    if (
        exact is not None
        and int(exact.get("read_model_version") or 0)
        >= PersistentRegionSnapshotService.READ_MODEL_VERSION
        and isinstance(exact.get("ai_report"), dict)
    ):
        return exact, "read-model"

    return _compatibility_region_read_model(region_key, year, month)


def _refresh_future_chart_points(report, region_key, selected_year, selected_month, active):
    """Use the current published series for months after a historical page."""
    if int(active["year"]) != int(selected_year) or int(active["month"]) <= int(selected_month):
        return report
    upload_id = active.get("upload_id")
    if not upload_id:
        return report
    current = PersistentRegionSnapshotService.get_active_for_visible_upload(
        region_key, active["year"], active["month"], upload_id
    )
    current_rows = ((current or {}).get("report") or {}).get("annual_realization") or []
    prior_rows = report.get("annual_realization") or []
    if not current_rows or not prior_rows:
        return report
    future = {
        int(row["month"]): row for row in current_rows
        if isinstance(row, dict) and row.get("month") is not None
        and int(selected_month) < int(row["month"]) <= int(active["month"])
    }
    if not future:
        return report
    updated = dict(report)
    updated["annual_realization"] = [
        future.get(int(row["month"]), row) if isinstance(row, dict) and row.get("month") is not None else row
        for row in prior_rows
    ]
    return updated


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

        if region_data_source == "read-model":
            # Active/current generations retain the snapshot publication gate.
            # Snapshot upgrades are worker-owned. A page request must remain a
            # bounded read even when an old generation is encountered.
            read_model_version = int(read_model.get("read_model_version") or 0)
            if (
                read_model is None
                or int(read_model.get("read_model_version") or 0)
                < PersistentRegionSnapshotService.READ_MODEL_VERSION
                or not isinstance(read_model.get("ai_report"), dict)
            ):
                flash(
                    "Bölge görünümü hazırlanıyor. Temsilci verileri tamamlandığında otomatik olarak hazır olacaktır.",
                    "info",
                )
                return redirect(url_for("dashboard.index"))

        current_report = _refresh_future_chart_points(
            read_model["report"], region_key, year, month, active
        )
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
