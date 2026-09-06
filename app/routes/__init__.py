from flask import Blueprint
from flask import current_app
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import url_for
from flask import request

from flask_login import current_user
from flask_login import login_required
from sqlalchemy import desc

from app.cache.region_manager_snapshot_cache import RegionManagerSnapshotCache
from app.extensions import db
from app.models import IMSUpload, Representative
from app.services.dashboard_service import DashboardService
from app.services.executive_market_cockpit_service import ExecutiveMarketCockpitService
from app.services.market_analysis_service import MarketAnalysisService
from app.services.period_service import PeriodService
from app.services.persistent_region_snapshot_service import PersistentRegionSnapshotService
from app.services.production_result_service import ProductionResultService
from app.services.quarter_entitlement_service import QuarterEntitlementService
from app.services.region_market_service import RegionMarketService
from app.services.region_performance_service import RegionPerformanceService


main_bp = Blueprint(
    "main",
    __name__
)


def _region_snapshot_key(region_key, year, month):
    latest_ims_id = db.session.query(IMSUpload.id).filter(
        IMSUpload.year == int(year),
        IMSUpload.month == int(month),
        IMSUpload.status == "COMPLETED",
    ).order_by(
        desc(IMSUpload.week_number), desc(IMSUpload.completed_at), desc(IMSUpload.id)
    ).limit(1).scalar()
    production_upload = ProductionResultService.final_upload(int(year), int(month))
    production_id = production_upload.id if production_upload is not None else 0
    return f"manager-region:{region_key}:{year}:{month}:{latest_ims_id or 0}:{production_id}:v1"


def _build_region_snapshot(region_key, year, month):
    performance = RegionPerformanceService(region_key, year, month)
    report = performance.report()
    market = RegionMarketService(
        report["region_key"], performance.rep_ids, year, month
    ).build()
    return {"report": report, "market_analysis": market}


def _region_manager_snapshot(region_key, year, month):
    persistent = PersistentRegionSnapshotService.get_active(region_key, year, month)
    if persistent is not None:
        return persistent

    key = _region_snapshot_key(region_key, year, month)
    return RegionManagerSnapshotCache.get_or_compute(
        key, lambda: _build_region_snapshot(region_key, year, month)
    )


def _render_region_snapshot(snapshot):
    return render_template(
        "partials/market_region_workspace.html",
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

    try:
        payload["competition_analysis"] = MarketAnalysisService(
            dashboard_service.year,
            dashboard_service.month,
        ).build()
    except Exception:
        current_app.logger.exception(
            "Türkiye Pazar Analizi national market read failed for %s/%s",
            dashboard_service.year,
            dashboard_service.month,
        )
        payload["competition_analysis"] = _empty_market_analysis(
            dashboard_service.year,
            dashboard_service.month,
            "Pazar verisi okunurken geçici bir hata oluştu. Bölgesel performans ekranı kullanılmaya devam edebilir.",
        )

    region_rows = payload.get("region_realization") or []
    selected_region = request.args.get("region") or (
        str(region_rows[0].get("code")) if region_rows else None
    )

    try:
        durable_snapshots = PersistentRegionSnapshotService.get_active_all(
            dashboard_service.year, dashboard_service.month
        ) or {}
    except Exception:
        current_app.logger.exception(
            "Türkiye Pazar Analizi durable region pack read failed for %s/%s",
            dashboard_service.year,
            dashboard_service.month,
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
                dashboard_service.year,
                dashboard_service.month,
            )

    try:
        executive_cockpit = ExecutiveMarketCockpitService.build(
            payload.get("competition_analysis") or {},
            usable_snapshots,
            region_rows,
        )
    except Exception:
        current_app.logger.exception(
            "Türkiye Pazar Analizi executive cockpit build failed for %s/%s",
            dashboard_service.year,
            dashboard_service.month,
        )
        executive_cockpit = ExecutiveMarketCockpitService.build(
            payload.get("competition_analysis") or {}, {}, region_rows
        )

    initial_region_snapshot = usable_snapshots.get(str(selected_region)) if selected_region else None
    if selected_region and initial_region_snapshot is None:
        try:
            initial_region_snapshot = _build_region_snapshot(
                selected_region, dashboard_service.year, dashboard_service.month
            )
            _render_region_snapshot(initial_region_snapshot)
        except ValueError:
            selected_region = None
            initial_region_snapshot = None
        except Exception:
            current_app.logger.exception(
                "Türkiye Pazar Analizi initial region build failed: region=%s period=%s/%s",
                selected_region,
                dashboard_service.year,
                dashboard_service.month,
            )
            selected_region = None
            initial_region_snapshot = None

    return render_template(
        "market_analysis.html",
        payload=payload,
        region_rows=region_rows,
        selected_region=selected_region,
        initial_region_snapshot=initial_region_snapshot,
        embedded_region_html=embedded_region_html,
        executive_cockpit=executive_cockpit,
        selected_year=dashboard_service.year,
        selected_month=dashboard_service.month,
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
        return render_template("partials/market_region_workspace_error.html", message=str(exc)), 404
    except Exception:
        current_app.logger.exception(
            "Türkiye Pazar Analizi region detail failed: region=%s period=%s/%s",
            region_key, year, month,
        )
        try:
            snapshot = _build_region_snapshot(region_key, year, month)
            return _render_region_snapshot(snapshot)
        except Exception:
            current_app.logger.exception(
                "Türkiye Pazar Analizi fresh region fallback failed: region=%s period=%s/%s",
                region_key, year, month,
            )
            return render_template(
                "partials/market_region_workspace_error.html",
                message="Bölge verisi geçici olarak hazırlanamadı. Ana Türkiye Pazar Analizi ekranı kullanılabilir.",
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
