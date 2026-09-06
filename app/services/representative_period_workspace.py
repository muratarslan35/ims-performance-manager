from __future__ import annotations

from collections import defaultdict
from copy import deepcopy

from flask import request, render_template
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Product, Representative, RepresentativeBrickAssignment, Target
from app.services.annual_realization_service import AnnualRealizationService
from app.services.competitive_intelligence_service import CompetitiveIntelligenceService
from app.services.period_service import PeriodService
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


def _aggregate_sales(representative_id, months):
    buckets = {}
    sources = set()
    assignments = []
    for year, month in months:
        if (year, month) == months[-1]:
            assignments = RepresentativeBrickAssignment.query.filter_by(
                representative_id=representative_id, year=year, month=month, active=True
            ).order_by(RepresentativeBrickAssignment.brick).all()
        targets = Target.query.filter_by(
            representative_id=representative_id, year=year, month=month
        ).join(Product).order_by(Product.display_order, Product.product_name).all()
        effective = ProductionResultService.effective_products(year, month, representative_id)
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
    totals = {"target_tl": 0.0, "actual_tl": 0.0, "target_unit": 0.0, "actual_unit": 0.0, "remaining_tl": 0.0}
    for bucket in buckets.values():
        bucket["percent"] = realization_percent(bucket["actual_tl"], bucket["target_tl"]) if bucket["target_tl"] else 0
        for key in totals:
            totals[key] += bucket[key]
        rows.append(bucket)
    rows.sort(key=lambda item: (getattr(item["product"], "display_order", 999), item["product"].product_name))
    totals = {key: round(value, 2) for key, value in totals.items()}
    totals["percent"] = realization_percent(totals["actual_tl"], totals["target_tl"]) if totals["target_tl"] else 0
    return rows, totals, assignments, sources


def _aggregate_market(representative, months):
    monthly = [RepresentativeMarketService(representative, year, month).build() for year, month in months]
    if not monthly:
        return RepresentativeMarketService(representative, months[-1][0], months[-1][1]).build()
    if len(monthly) == 1:
        return monthly[0]

    result = deepcopy(monthly[-1])
    product_rows = {}
    for payload in monthly:
        for row in payload.get("rows", []):
            pid = int(row["product"].id)
            bucket = product_rows.setdefault(pid, deepcopy(row))
            if bucket is row:
                continue
            if payload is monthly[0]:
                continue
            for key in ("actual_unit", "market_unit", "competitor_unit", "target_unit"):
                bucket[key] = float(bucket.get(key) or 0) + float(row.get(key) or 0)
            rivals = defaultdict(float)
            for existing in bucket.get("rivals", []):
                rivals[existing["name"]] += float(existing.get("unit") or 0)
            for rival in row.get("rivals", []):
                rivals[rival["name"]] += float(rival.get("unit") or 0)
            bucket["rivals"] = [{"name": name, "unit": round(unit, 2)} for name, unit in sorted(rivals.items(), key=lambda item: -item[1])]
    rows = list(product_rows.values())
    for row in rows:
        row["share_percent"] = round(row["actual_unit"] * 100.0 / row["market_unit"], 1) if row["market_unit"] else 0.0
        row["gap_unit"] = round(row["competitor_unit"] - row["actual_unit"], 2)
        row["realization_percent"] = realization_percent(row["actual_unit"], row["target_unit"]) if row["target_unit"] else 0
        row["attention"] = "critical" if row["competitor_unit"] > row["actual_unit"] * 1.5 and row["competitor_unit"] > 0 else "warning" if row["competitor_unit"] > row["actual_unit"] else "strong"
    rows.sort(key=lambda item: getattr(item["product"], "display_order", 999))
    result["rows"] = rows
    result["chart_rows"] = [{"product_name": row["product"].product_name, "actual_unit": row["actual_unit"], "competitor_unit": row["competitor_unit"]} for row in rows]
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


def _ai_period(key, label, rows, totals):
    return {
        "key": key,
        "label": label,
        "month_count": 1,
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


def install_representative_period_workspace(app):
    from app.representatives import _representative_display_name, _visible_representative_filter
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
        months = _period_months(year, month, selected)
        if not months:
            months = [(year, month)]

        product_rows, totals, assignments, sources = _aggregate_sales(representative.id, months)
        has_production_result = any(source.startswith("PRODUCTION_") for source in sources)
        result_source_label = "Dönemsel P2 > P1 > IMS toplamı" if len(months) > 1 else (
            "2. üretim nihai sonucu" if "PRODUCTION_2" in sources else "1. üretim sonucu" if has_production_result else "Seçili IMS dönemine kadar"
        )
        market_analysis = _aggregate_market(representative, months)
        competitive_intelligence = CompetitiveIntelligenceService(representative.id, year, month).build()
        label = PERIOD_LABELS[selected]
        ai_report = ScopedAIInsightService.build(
            scope_type="representative",
            scope_name=_representative_display_name(representative.rep_name),
            periods={selected: _ai_period(selected, label, product_rows, totals)},
            market_analysis=market_analysis,
            competitive_intelligence=competitive_intelligence,
        )
        annual_realization = AnnualRealizationService.build(year, [representative.id])
        if is_field_portal():
            from app.region_manager import _scoped_representatives
            representatives = _scoped_representatives(active_only=True)
        else:
            representatives = Representative.query.filter(
                Representative.active.is_(True), _visible_representative_filter()
            ).order_by(Representative.rep_name.asc()).all()

        html = render_template(
            "representative_detail.html",
            representative=representative,
            representatives=representatives,
            assignments=assignments,
            products=product_rows,
            totals=totals,
            market_analysis=market_analysis,
            annual_realization=annual_realization,
            has_production_result=has_production_result,
            result_source_label=result_source_label,
            ai_report=ai_report,
            year=year,
            month=month,
            selected_period=selected,
        )
        selector = _selector_html(representative.id, year, month, selected)
        marker = '<section class="scope-ai"'
        if marker in html:
            html = html.replace(marker, selector + marker, 1)
        return html

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
                body = body.replace("</head>", '<link rel="stylesheet" href="/static/css/representative-period-workspace.css"></head>', 1)
                response.set_data(body)
        return response


def _selector_html(representative_id, year, month, selected):
    def button(key, label, wide=False):
        active = " active" if key == selected else ""
        return (
            f'<a class="rep-period-btn{active}" data-rep-period="{key}" '
            f'href="/representatives/view/{representative_id}?year={year}&month={month}&period={key}">{label}</a>'
        )
    top = "".join(button(key, label, True) for key, label, kind in PERIOD_OPTIONS if kind == "wide")
    bottom = "".join(button(key, label) for key, label, kind in PERIOD_OPTIONS if kind == "compact")
    return (
        '<section class="rep-period-workspace" aria-label="Temsilci dönem görünümü">'
        '<div class="rep-period-row rep-period-row-wide">' + top + '</div>'
        '<div class="rep-period-row rep-period-row-compact">' + bottom + '</div>'
        '</section>'
    )
