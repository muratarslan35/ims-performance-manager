from flask import Blueprint
from flask import abort
from flask import current_app
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import url_for
from flask import request
from flask import send_file

from flask_login import current_user
from flask_login import login_required
from functools import wraps
from app.models import Representative
from app.services.historical_region_read_model_service import HistoricalRegionReadModelService
from app.services.executive_market_cockpit_service import ExecutiveMarketCockpitService
from app.services.market_analysis_service import MarketAnalysisService
from app.services.period_service import PeriodService
from app.services.persistent_dashboard_snapshot_service import PersistentDashboardSnapshotService
from app.services.persistent_region_snapshot_service import PersistentRegionSnapshotService
from app.services.quarter_entitlement_service import QuarterEntitlementService
from app.services.executive_reporting_service import ExecutiveReportingService
from app.services.report_cache_service import ReportCacheService
from app.services.report_export_queue import ReportExportQueue


main_bp = Blueprint(
    "main",
    __name__
)


def reports_access_required(view):
    """Enforce report permission on the page and every queued-export endpoint."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        from app.services.access_permission_service import enabled as access_enabled
        if not access_enabled(current_user, "reports"):
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def _region_manager_snapshot(region_key, year, month):
    """Read manager region detail without rebuilding current source data in HTTP."""
    persistent = PersistentRegionSnapshotService.get_active(region_key, year, month)
    if persistent is not None:
        return persistent

    active = PeriodService.get_active_period()
    if (
        int(year) == int(active["year"])
        and int(month) == int(active["month"])
    ):
        raise RuntimeError("Güncel bölge read-modeli henüz hazır değil.")

    return HistoricalRegionReadModelService.get_or_build(region_key, year, month)


def _render_region_snapshot(snapshot):
    """Render one snapshot partial without re-running app context processors.

    The partial is intentionally self-contained: it only consumes the persisted
    report + market payload. render_template would execute every Flask context
    processor for each region and multiply permission/period metadata SELECTs
    inside a single Türkiye Pazar request.
    """
    template = current_app.jinja_env.get_template(
        "partials/market_region_workspace.html"
    )
    return template.render(
        report=snapshot["report"],
        market_analysis=snapshot["market_analysis"],
    )


def _empty_market_analysis(year, month, message):
    return {
        "year": int(year),
        "month": int(month),
        "latest_week": None,
        "source_week": None,
        "source_state": MarketAnalysisService.SOURCE_IMS_ONLY,
        "is_current": False,
        "is_fallback": False,
        "has_competition": False,
        "source_message": message,
        "source_file": None,
        "market_total_tl": 0.0,
        "company_total_tl": 0.0,
        "competitor_total_tl": 0.0,
        "company_share_percent": 0.0,
        "groups": [],
    }


@main_bp.route("/")
@login_required
def home():
    """Always enter through the canonical dashboard route with a populated payload."""
    return redirect(url_for("dashboard.index"))


@main_bp.route("/dashboard")
@login_required
def dashboard():
    return redirect(
        url_for("dashboard.index")
    )


@main_bp.route("/market-analysis")
@login_required
def market_analysis():
    active = PeriodService.get_active_period()
    year, month = int(active["year"]), int(active["month"])

    # The IMS worker publishes dashboard + national market in one durable
    # read-model. HTTP requests never rebuild either calculation chain.
    payload = PersistentDashboardSnapshotService.get_active(year, month) or {}
    payload = dict(payload)
    competition_analysis = payload.get("competition_analysis")
    if not isinstance(competition_analysis, dict):
        competition_analysis = _empty_market_analysis(
            year,
            month,
            "Türkiye pazar read-modeli hazırlanıyor. Hazır bölgesel snapshotlar kullanılmaya devam edebilir.",
        )
    payload["competition_analysis"] = competition_analysis

    region_rows = payload.get("region_realization") or []
    selected_region = request.args.get("region") or (
        str(region_rows[0].get("code")) if region_rows else None
    )

    try:
        durable_snapshots = PersistentRegionSnapshotService.get_active_all(
            year, month
        ) or {}
    except Exception:
        current_app.logger.exception(
            "Türkiye Pazar Analizi durable region pack read failed for %s/%s",
            year,
            month,
        )
        durable_snapshots = {}

    embedded_region_html = {}
    usable_snapshots = {}
    for region_key, snapshot in durable_snapshots.items():
        try:
            embedded_region_html[str(region_key)] = _render_region_snapshot(snapshot)
            usable_snapshots[str(region_key)] = snapshot
        except Exception:
            current_app.logger.exception(
                "Türkiye Pazar Analizi stale/invalid cached region snapshot skipped: region=%s period=%s/%s",
                region_key,
                year,
                month,
            )

    try:
        executive_cockpit = ExecutiveMarketCockpitService.build(
            competition_analysis,
            usable_snapshots,
            region_rows,
        )
    except Exception:
        current_app.logger.exception(
            "Türkiye Pazar Analizi executive cockpit build failed for %s/%s",
            year,
            month,
        )
        executive_cockpit = ExecutiveMarketCockpitService.build(
            competition_analysis, {}, region_rows
        )

    initial_region_snapshot = (
        usable_snapshots.get(str(selected_region)) if selected_region else None
    )
    if selected_region and initial_region_snapshot is None:
        # Current-period manager UI remains snapshot-gated. The background
        # worker owns rebuilds; a user click must never launch source queries.
        selected_region = None

    return render_template(
        "market_analysis.html",
        payload=payload,
        region_rows=region_rows,
        selected_region=selected_region,
        initial_region_snapshot=initial_region_snapshot,
        embedded_region_html=embedded_region_html,
        executive_cockpit=executive_cockpit,
        selected_year=year,
        selected_month=month,
    )

@main_bp.route("/market-analysis/regions-pack")
@login_required
def market_analysis_regions_pack():
    """Return the complete manager region cockpit from one durable snapshot read."""
    active = PeriodService.get_active_period()
    year = request.args.get("year", active["year"], type=int)
    month = request.args.get("month", active["month"], type=int)
    snapshots = PersistentRegionSnapshotService.get_active_all(year, month)
    if not snapshots:
        return jsonify({"ready": False, "regions": {}}), 409

    regions = {}
    for region_key, snapshot in snapshots.items():
        try:
            regions[str(region_key)] = _render_region_snapshot(snapshot)
        except Exception:
            current_app.logger.exception(
                "Türkiye Pazar Analizi region pack skipped invalid snapshot: region=%s period=%s/%s",
                region_key, year, month,
            )
    if not regions:
        return jsonify({"ready": False, "regions": {}}), 409

    ims_id, production_id = PersistentRegionSnapshotService.source_identity(year, month)
    response = jsonify({
        "ready": True,
        "year": year,
        "month": month,
        "ims_upload_id": ims_id,
        "production_upload_id": production_id,
        "regions": regions,
    })
    response.headers["Cache-Control"] = "private, no-cache"
    return response


@main_bp.route("/market-analysis/region/<path:region_key>")
@login_required
def market_analysis_region(region_key):
    active = PeriodService.get_active_period()
    year = request.args.get("year", active["year"], type=int)
    month = request.args.get("month", active["month"], type=int)
    try:
        snapshot = _region_manager_snapshot(region_key, year, month)
        return _render_region_snapshot(snapshot)
    except ValueError as exc:
        return render_template(
            "partials/market_region_workspace_error.html", message=str(exc)
        ), 404
    except Exception:
        current_app.logger.exception(
            "Türkiye Pazar Analizi region read-model unavailable: region=%s period=%s/%s",
            region_key, year, month,
        )
        return render_template(
            "partials/market_region_workspace_error.html",
            message="Bölge verisi hazırlanıyor. Ana Türkiye Pazar Analizi ekranı kullanılabilir.",
        ), 503


@main_bp.route("/prime")
@login_required
def prime():
    return render_template(
        "prime.html",
        user=current_user
    )


@main_bp.route("/reports")
@login_required
@reports_access_required
def reports():
    scope = request.args.get("scope", "national")
    scope_values = request.args.getlist("scope_value")
    scope_value = scope_values[0] if scope_values else request.args.get("scope_value", "")
    if not scope_values and scope_value:
        scope_values = [scope_value]

    from app.region_manager import assigned_region, is_regional_manager
    if is_regional_manager(current_user):
        scope_value = assigned_region(current_user) or ""
        scope, scope_values = "region", ([scope_value] if scope_value else [])

    service = ExecutiveReportingService(
        year=request.args.get("year", type=int),
        month=request.args.get("month", type=int),
        period=request.args.get("period", "monthly"),
        scope=scope,
        scope_value=scope_value,
        scope_values=scope_values,
        product_ids=request.args.getlist("product_id"),
    )
    return render_template(
        "reports.html",
        user=current_user,
        options=ReportCacheService.get_filter_options(service),
        filters=service,
    )


def _authorized_report_job(job):
    if not job:
        return False
    from app.region_manager import assigned_region, is_regional_manager
    if not is_regional_manager(current_user):
        return True
    assigned = ExecutiveReportingService._region_code(assigned_region(current_user) or "")
    requested_values = job.get("scope_values") or [job.get("scope_value") or ""]
    requested = {
        ExecutiveReportingService._region_code(value) or str(value or "").strip()
        for value in requested_values if str(value or "").strip()
    }
    return (
        job.get("scope") == "region"
        and bool(assigned)
        and requested == {assigned}
    )


@main_bp.route("/reports/export/<file_type>")
@login_required
@reports_access_required
def reports_export(file_type):
    if file_type not in {"xlsx", "pdf", "pptx"}:
        return {"success": False, "message": "Desteklenmeyen rapor biçimi."}, 404
    scope = request.args.get("scope", "national")
    scope_values = request.args.getlist("scope_value")
    scope_value = scope_values[0] if scope_values else request.args.get("scope_value", "")
    if not scope_values and scope_value:
        scope_values = [scope_value]
    from app.region_manager import assigned_region, is_regional_manager
    if is_regional_manager(current_user):
        scope_value = assigned_region(current_user) or ""
        scope, scope_values = "region", ([scope_value] if scope_value else [])
    service = ExecutiveReportingService(
        year=request.args.get("year", type=int), month=request.args.get("month", type=int),
        period=request.args.get("period", "monthly"), scope=scope,
        scope_value=scope_value, scope_values=scope_values,
        product_ids=request.args.getlist("product_id"),
    )
    cache_key, _identity = ReportCacheService.identity(service)
    report = ReportCacheService.read_by_key(cache_key)
    filename = service.export_filename(
        report or {
            "scope_label": service.scope_label(),
            "year": service.year,
            "month": service.month,
        },
        file_type,
    )
    cached = ReportCacheService.cached_export(cache_key, file_type)
    if cached is not None:
        return send_file(
            cached,
            as_attachment=True,
            download_name=filename,
            mimetype={
                "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "pdf": "application/pdf",
                "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            }[file_type],
            conditional=True,
        )

    job = ReportExportQueue.enqueue(
        cache_key=cache_key,
        file_type=file_type,
        filename=filename,
        scope=scope,
        scope_value=scope_value,
        scope_values=scope_values,
        year=service.year,
        month=service.month,
        period=service.period,
        product_ids=service.product_ids,
    )
    return jsonify({
        "success": True,
        "status": job["status"],
        "job_id": job["job_id"],
        "position": ReportExportQueue.position(job["job_id"]),
        "status_url": url_for("main.reports_export_status", job_id=job["job_id"]),
    }), 202


@main_bp.route("/reports/export/status/<job_id>")
@login_required
@reports_access_required
def reports_export_status(job_id):
    job = ReportExportQueue.read(job_id)
    if not _authorized_report_job(job):
        return jsonify({"success": False, "message": "Rapor işi bulunamadı."}), 404

    payload = {
        "success": True,
        "job_id": job["job_id"],
        "status": job["status"],
        "position": ReportExportQueue.position(job["job_id"]),
        "error": job.get("error"),
    }
    if job["status"] == ReportExportQueue.STATUS_COMPLETED:
        cached = ReportCacheService.cached_export(job["cache_key"], job["file_type"])
        if cached is not None:
            payload["download_url"] = url_for("main.reports_export_download", job_id=job["job_id"])
        else:
            payload["status"] = ReportExportQueue.STATUS_FAILED
            payload["error"] = "Hazırlanan rapor dosyası bulunamadı."
    return jsonify(payload)


@main_bp.route("/reports/export/download/<job_id>")
@login_required
@reports_access_required
def reports_export_download(job_id):
    job = ReportExportQueue.read(job_id)
    if not _authorized_report_job(job):
        return jsonify({"success": False, "message": "Rapor işi bulunamadı."}), 404
    if job.get("status") != ReportExportQueue.STATUS_COMPLETED:
        return jsonify({"success": False, "message": "Rapor henüz hazır değil."}), 409

    cached = ReportCacheService.cached_export(job["cache_key"], job["file_type"])
    if cached is None:
        return jsonify({"success": False, "message": "Rapor dosyası bulunamadı."}), 404
    return send_file(
        cached,
        as_attachment=True,
        download_name=job["filename"],
        mimetype={
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "pdf": "application/pdf",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }[job["file_type"]],
        conditional=True,
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

    quarter_months = list(range((quarter - 1) * 3 + 1, (quarter - 1) * 3 + 4)) if quarter in (1, 2, 3, 4) else []
    quota_exit_by_month = {}
    for month in quarter_months:
        key = f"quota_exit_{month}"
        if key not in request.args:
            continue
        raw_value = (request.args.get(key) or "").strip()
        quota_exit_by_month[month] = int(raw_value) if raw_value.isdigit() else None

    if representative_id:
        selected_representative = Representative.query.get_or_404(representative_id)
        report = QuarterEntitlementService(
            representative_id,
            year,
            quarter,
            quota_exit_by_month=quota_exit_by_month,
        ).report()
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
