from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from hashlib import sha1

from flask import request, render_template
from flask_login import current_user, login_required

from app.cache.representative_analysis_cache import RepresentativeAnalysisCache
from app.models import Product, Representative, RepresentativeBrickAssignment, Target
from app.presentation import representative_display_name
from app.services.annual_realization_service import AnnualRealizationService
from app.services.competitive_intelligence_service import CompetitiveIntelligenceService
from app.services.period_service import PeriodService
from app.services.persistent_representative_snapshot_service import PersistentRepresentativeSnapshotService
from app.services.production_result_service import ProductionResultService
from app.services.realization_rounding import realization_percent
from app.services.representative_market_service import RepresentativeMarketService
from app.services.scoped_ai_insight_service import ScopedAIInsightService


PERIOD_OPTIONS = (
    ("half_year", "6 Aylık", "wide"),
    ("yearly", "YILLIK YTD", "wide"),
    ("monthly", "Aylık", "compact"),
    ("q1", "Q1", "compact"),
    ("q2", "Q2", "compact"),
    ("q3", "Q3", "compact"),
    ("q4", "Q4", "compact"),
)
PERIOD_LABELS = {key: label for key, label, _ in PERIOD_OPTIONS}


def _shift_month(year, month, delta):
    ordinal = int(year) * 12 + int(month) - 1 + int(delta)
    return ordinal // 12, ordinal % 12 + 1


def _period_months(year, month, key):
    year, month = int(year), int(month)
    if key == "monthly":
        return [(year, month)]
    if key == "half_year":
        return [_shift_month(year, month, delta) for delta in range(-5, 1)]
    if key == "yearly":
        return [(year, value) for value in range(1, month + 1)]
    if key in {"q1", "q2", "q3", "q4"}:
        quarter = int(key[1])
        start = (quarter - 1) * 3 + 1
        return [(year, value) for value in range(start, start + 3) if value <= month]
    return [(year, month)]


def _empty_totals():
    return {
        "target_tl": 0.0,
        "actual_tl": 0.0,
        "target_unit": 0.0,
        "actual_unit": 0.0,
        "remaining_tl": 0.0,
        "percent": 0,
    }


def _empty_market(year, month):
    previous_year, previous_month = _shift_month(year, month, -1)
    return {
        "scope": "none",
        "bricks": [],
        "rows": [],
        "chart_rows": [],
        "brick_product_rows": [],
        "totals": {
            "actual_unit": 0.0,
            "market_unit": 0.0,
            "competitor_unit": 0.0,
            "share_percent": 0.0,
        },
        "previous_period": {"year": previous_year, "month": previous_month},
        "period_months": [],
    }


def _aggregate_sales(representative_id, months, sales_cache=None, assignment_cache=None):
    if not months:
        return [], _empty_totals(), [], set()

    sales_cache = sales_cache if sales_cache is not None else {}
    assignment_cache = assignment_cache if assignment_cache is not None else {}
    buckets = {}
    sources = set()
    assignments = []

    for year, month in months:
        cache_key = (int(year), int(month))
        cached = sales_cache.get(cache_key)
        if cached is None:
            targets = Target.query.filter_by(
                representative_id=representative_id, year=year, month=month
            ).join(Product).order_by(Product.display_order, Product.product_name).all()
            effective = ProductionResultService.effective_products(year, month, representative_id)
            cached = (targets, effective)
            sales_cache[cache_key] = cached
        else:
            targets, effective = cached

        if cache_key == months[-1]:
            assignments = assignment_cache.get(cache_key)
            if assignments is None:
                assignments = RepresentativeBrickAssignment.query.filter_by(
                    representative_id=representative_id, year=year, month=month, active=True
                ).order_by(RepresentativeBrickAssignment.brick).all()
                assignment_cache[cache_key] = assignments

        for target in targets:
            resolved = effective.get(target.product_id, {})
            target_tl = float(resolved.get("target_tl", target.tl_target or 0.0))
            actual_tl = float(resolved.get("actual_tl", 0.0))
            target_unit = float(resolved.get("target_unit", target.unit_target or 0.0))
            actual_unit = float(resolved.get("actual_unit", 0.0))
            source = resolved.get("source", "IMS")
            sources.add(source)
            bucket = buckets.setdefault(target.product_id, {
                "product": target.product,
                "target_tl": 0.0,
                "actual_tl": 0.0,
                "target_unit": 0.0,
                "actual_unit": 0.0,
                "remaining_tl": 0.0,
                "source": source,
            })
            bucket["target_tl"] += target_tl
            bucket["actual_tl"] += actual_tl
            bucket["target_unit"] += target_unit
            bucket["actual_unit"] += actual_unit
            bucket["remaining_tl"] += max(target_tl - actual_tl, 0.0)
            if source == "PRODUCTION_2" or (source == "PRODUCTION_1" and bucket["source"] == "IMS"):
                bucket["source"] = source

    rows = []
    totals = {
        "target_tl": 0.0,
        "actual_tl": 0.0,
        "target_unit": 0.0,
        "actual_unit": 0.0,
        "remaining_tl": 0.0,
    }
    for bucket in buckets.values():
        bucket["percent"] = realization_percent(bucket["actual_tl"], bucket["target_tl"]) if bucket["target_tl"] else 0
        for key in totals:
            totals[key] += bucket[key]
        rows.append(bucket)
    rows.sort(key=lambda item: (getattr(item["product"], "display_order", 999), item["product"].product_name))
    totals = {key: round(value, 2) for key, value in totals.items()}
    totals["percent"] = realization_percent(totals["actual_tl"], totals["target_tl"]) if totals["target_tl"] else 0
    return rows, totals, assignments, sources


def _market_source_cache_key(representative, year, month):
    """Key the exact existing market read by immutable source/scope identity."""
    year, month = int(year), int(month)
    previous_year, previous_month = _shift_month(year, month, -1)
    upload_id = RepresentativeMarketService._latest_upload_id(year, month) or 0
    previous_upload_id = RepresentativeMarketService._latest_upload_id(previous_year, previous_month) or 0
    production_upload = ProductionResultService.final_upload(year, month)
    production_upload_id = int(production_upload.id) if production_upload else 0
    assignments = RepresentativeBrickAssignment.query.filter_by(
        representative_id=representative.id, year=year, month=month, active=True
    ).order_by(RepresentativeBrickAssignment.brick).all()
    scope_material = "|".join(
        [
            str(representative.id),
            str(representative.region or ""),
            str(representative.city or ""),
            str(representative.territory or ""),
            *[str(item.brick or "") for item in assignments],
        ]
    )
    scope_digest = sha1(scope_material.encode("utf-8")).hexdigest()[:16]
    return (
        f"rep-market:{representative.id}:{year}:{month}:"
        f"{upload_id}:{previous_upload_id}:{production_upload_id}:{scope_digest}:workspace-v1"
    )


def _aggregate_market(representative, months, market_cache=None):
    if not months:
        active = PeriodService.get_active_period()
        return _empty_market(active["year"], active["month"])

    market_cache = market_cache if market_cache is not None else {}
    monthly = []
    for year, month in months:
        cache_key = (int(year), int(month))
        payload = market_cache.get(cache_key)
        if payload is None:
            source_cache_key = _market_source_cache_key(representative, year, month)
            payload = RepresentativeAnalysisCache.get_or_compute(
                source_cache_key,
                lambda y=year, m=month: RepresentativeMarketService(representative, y, m).build(),
                ttl_seconds=45,
            )
            market_cache[cache_key] = payload
        monthly.append(payload)

    if len(monthly) == 1:
        return deepcopy(monthly[0])

    result = deepcopy(monthly[-1])
    product_rows = {}
    for payload in monthly:
        for row in payload.get("rows", []):
            pid = int(row["product"].id)
            if pid not in product_rows:
                product_rows[pid] = deepcopy(row)
                continue
            bucket = product_rows[pid]
            for key in ("actual_unit", "market_unit", "competitor_unit", "target_unit"):
                bucket[key] = float(bucket.get(key) or 0) + float(row.get(key) or 0)
            rivals = defaultdict(float)
            for existing in bucket.get("rivals", []):
                rivals[existing["name"]] += float(existing.get("unit") or 0)
            for rival in row.get("rivals", []):
                rivals[rival["name"]] += float(rival.get("unit") or 0)
            bucket["rivals"] = [
                {"name": name, "unit": round(unit, 2)}
                for name, unit in sorted(rivals.items(), key=lambda item: -item[1])
            ]

    rows = list(product_rows.values())
    for row in rows:
        row["share_percent"] = round(row["actual_unit"] * 100.0 / row["market_unit"], 1) if row["market_unit"] else 0.0
        row["gap_unit"] = round(row["competitor_unit"] - row["actual_unit"], 2)
        row["realization_percent"] = realization_percent(row["actual_unit"], row["target_unit"]) if row["target_unit"] else 0
        row["attention"] = (
            "critical" if row["competitor_unit"] > row["actual_unit"] * 1.5 and row["competitor_unit"] > 0
            else "warning" if row["competitor_unit"] > row["actual_unit"]
            else "strong"
        )
    rows.sort(key=lambda item: getattr(item["product"], "display_order", 999))
    result["rows"] = rows
    result["chart_rows"] = [
        {
            "product_name": row["product"].product_name,
            "actual_unit": row["actual_unit"],
            "competitor_unit": row["competitor_unit"],
        }
        for row in rows
    ]
    total_actual = sum(float(row.get("actual_unit") or 0) for row in rows)
    total_market = sum(float(row.get("market_unit") or 0) for row in rows)
    result["totals"] = {
        "actual_unit": round(total_actual, 2),
        "market_unit": round(total_market, 2),
        "competitor_unit": round(max(total_market - total_actual, 0.0), 2),
        "share_percent": round(total_actual * 100.0 / total_market, 1) if total_market else 0.0,
    }
    result["period_months"] = [{"year": y, "month": m} for y, m in months]
    return result


def _ai_period(key, label, rows, totals, month_count):
    return {
        "key": key,
        "label": label,
        "month_count": month_count,
        "target_tl": totals["target_tl"],
        "actual_tl": totals["actual_tl"],
        "realization_percent": totals["percent"],
        "gap_tl": totals["target_tl"] - totals["actual_tl"],
        "complete": True,
        "products": [{
            "product_id": row["product"].id,
            "product_name": row["product"].product_name,
            "target_tl": row["target_tl"],
            "actual_tl": row["actual_tl"],
            "realization_percent": row["percent"],
            "gap_tl": row["target_tl"] - row["actual_tl"],
            "complete": True,
        } for row in rows],
        "representatives": [],
    }


def _source_label(months, sources):
    if len(months) > 1:
        return "Dönemsel P2 > P1 > IMS toplamı"
    has_production_result = any(source.startswith("PRODUCTION_") for source in sources)
    if "PRODUCTION_2" in sources:
        return "2. üretim nihai sonucu"
    if has_production_result:
        return "1. üretim sonucu"
    return "Seçili IMS dönemine kadar"


def build_representative_workspace_payload(representative, year, month):
    """Build the exact existing representative read model once.

    This function intentionally contains the same calculation path the route used
    before persistent snapshots. The snapshot layer only stores this result.
    """
    year, month = int(year), int(month)
    sales_cache = {}
    assignment_cache = {}
    market_cache = {}
    competitive_intelligence = CompetitiveIntelligenceService(
        representative.id, year, month
    ).build()
    annual_realization = AnnualRealizationService.build(year, [representative.id])
    snapshots = {}

    for key, label, _kind in PERIOD_OPTIONS:
        months = _period_months(year, month, key)
        product_rows, totals, assignments, sources = _aggregate_sales(
            representative.id,
            months,
            sales_cache=sales_cache,
            assignment_cache=assignment_cache,
        )
        has_production_result = any(source.startswith("PRODUCTION_") for source in sources)
        result_source_label = _source_label(months, sources)
        market_analysis = (
            _aggregate_market(representative, months, market_cache=market_cache)
            if months else _empty_market(year, month)
        )
        ai_report = ScopedAIInsightService.build(
            scope_type="representative",
            scope_name=representative_display_name(representative.rep_name),
            periods={key: _ai_period(key, label, product_rows, totals, len(months))},
            market_analysis=market_analysis,
            competitive_intelligence=competitive_intelligence,
        )
        snapshots[key] = {
            "key": key,
            "label": label,
            "months": months,
            "products": product_rows,
            "totals": totals,
            "assignments": assignments,
            "market_analysis": market_analysis,
            "has_production_result": has_production_result,
            "result_source_label": result_source_label,
            "ai_report": ai_report,
        }

    return {
        "year": year,
        "month": month,
        "annual_realization": annual_realization,
        "snapshots": snapshots,
    }


def install_representative_period_workspace(app):
    from app.representatives import _visible_representative_filter
    from app.region_manager import is_field_portal

    @login_required
    def period_view(id):
        representative = Representative.query.get_or_404(id)
        if is_field_portal():
            from app.region_manager import can_access_representative
            if not can_access_representative(current_user, representative):
                from flask import flash, redirect, url_for
                flash("Sadece kendi bölgenizdeki temsilcilere erişebilirsiniz.", "warning")
                return redirect(url_for("dashboard.index"))

        active = PeriodService.get_active_period()
        year = request.args.get("year", type=int) or active["year"]
        month = request.args.get("month", type=int) or active["month"]
        selected = (request.args.get("period") or "monthly").strip().lower()
        if selected not in PERIOD_LABELS:
            selected = "monthly"

        workspace = PersistentRepresentativeSnapshotService.get_active(
            representative.id, year, month
        )
        if workspace is None:
            # Safe compatibility path only. Normal production flow builds durable
            # snapshots automatically in the background before a user needs them.
            workspace = build_representative_workspace_payload(representative, year, month)
        snapshots = workspace["snapshots"]
        annual_realization = workspace["annual_realization"]

        if is_field_portal():
            from app.region_manager import _scoped_representatives
            representatives = _scoped_representatives(active_only=True)
        else:
            representatives = Representative.query.filter(
                Representative.active.is_(True), _visible_representative_filter()
            ).order_by(Representative.rep_name.asc()).all()

        active_snapshot = snapshots[selected]
        return render_template(
            "representative_detail.html",
            representative=representative,
            representatives=representatives,
            assignments=active_snapshot["assignments"],
            products=active_snapshot["products"],
            totals=active_snapshot["totals"],
            market_analysis=active_snapshot["market_analysis"],
            annual_realization=annual_realization,
            has_production_result=active_snapshot["has_production_result"],
            result_source_label=active_snapshot["result_source_label"],
            ai_report=active_snapshot["ai_report"],
            year=year,
            month=month,
            selected_period=selected,
            period_options=PERIOD_OPTIONS,
            period_snapshots=snapshots,
            active_snapshot=active_snapshot,
        )

    app.view_functions["representatives.view"] = period_view

    @app.after_request
    def representative_period_assets(response):
        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type or not response.direct_passthrough:
            try:
                body = response.get_data(as_text=True)
            except Exception:
                return response
            if "</head>" in body and "representative-period-workspace.css" not in body:
                body = body.replace(
                    "</head>",
                    '<link rel="stylesheet" href="/static/css/representative-period-workspace.css"></head>',
                    1,
                )
                response.set_data(body)
        return response
