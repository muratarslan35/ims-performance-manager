from flask import Blueprint
from flask import flash
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for

from flask_login import login_required
from flask_login import current_user
from sqlalchemy import or_
import unicodedata
import re
from datetime import datetime

from app.extensions import db
from app.models import IMSSummary, Product, Representative, RepresentativeBrickAssignment, Target
from app.services.period_service import PeriodService
from app.services.representative_market_service import RepresentativeMarketService
from app.services.annual_realization_service import AnnualRealizationService


representatives_bp = Blueprint(

    "representatives",

    __name__,

    url_prefix="/representatives"

)


def _search_key(value):
    """Turkish-aware, accent-insensitive key used by the global search."""
    value = (value or "").translate(str.maketrans({"ı": "i", "İ": "I"})).casefold()
    return "".join(char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char))


def _representative_display_name(value):
    """Remove the technical vacancy prefix without changing the stored identity."""
    display_name = re.sub(
        r"^\s*ATANMAMI[ŞS]\s*(?:[·\-–—:]\s*)?", "", str(value or ""), flags=re.IGNORECASE
    ).strip()
    # Canonical vacancy names contain both a region context and a vacancy name:
    # "901 DIYARBAKIR · DIYARBAKIR BOS". Keep the region code without
    # repeating the city, yielding "901 DIYARBAKIR BOS".
    context, separator, vacancy_name = display_name.partition("·")
    region_code = re.match(r"^\s*(\d+)\b", context)
    if separator and region_code and vacancy_name.strip():
        return f"{region_code.group(1)} {vacancy_name.strip()}"
    return display_name


def _visible_representative_filter():
    """Hide only the non-regional general placeholder from representative UI."""
    return ~or_(
        db.func.coalesce(Representative.rep_code, "").ilike("UNASSIGNEDGENERAL%"),
        db.func.coalesce(Representative.rep_name, "").ilike("ATANMAMIŞ%GENEL%"),
        db.func.coalesce(Representative.rep_name, "").ilike("ATANMAMIS%GENEL%"),
    )


representatives_bp.add_app_template_filter(_representative_display_name, "representative_display_name")


@representatives_bp.route(

    "/"

)
@login_required
def index():

    latest = RepresentativeBrickAssignment.query.order_by(
        RepresentativeBrickAssignment.year.desc(), RepresentativeBrickAssignment.month.desc()
    ).first()
    assignments_by_rep = {}
    if latest:
        rows = RepresentativeBrickAssignment.query.filter_by(year=latest.year, month=latest.month, active=True).order_by(
            RepresentativeBrickAssignment.brick.asc()
        ).all()
        for assignment in rows:
            assignments_by_rep.setdefault(assignment.representative_id, []).append(assignment)

    # Regional vacancy portfolios carry targets and must remain selectable;
    # only the duplicate general placeholder is omitted from the UI.
    representatives = Representative.query.filter(_visible_representative_filter()).order_by(
        Representative.region.asc().nullslast(), Representative.city.asc(), Representative.rep_name.asc()
    ).all()

    return render_template(

        "representatives.html",

        representatives=representatives,
        assignments_by_rep=assignments_by_rep,
        assignment_period=(latest.year, latest.month) if latest else None,

    )


@representatives_bp.route(

    "/add",

    methods=["POST"]

)
@login_required
def add():

    try:

        representative = Representative(

            rep_code=request.form.get(

                "rep_code"

            ).strip(),

            ims_code=request.form.get(

                "ims_code"

            ).strip(),

            sap_code=request.form.get(

                "sap_code"

            ).strip(),

            rep_name=request.form.get(

                "rep_name"

            ).strip(),

            region=request.form.get(

                "region"

            ),

            city=request.form.get(

                "city"

            ),

            district=request.form.get(

                "district"

            ),

            territory=request.form.get(

                "territory"

            ),

            manager=request.form.get(

                "manager"

            ),

            team=request.form.get(

                "team"

            ),

            email=request.form.get(

                "email"

            ),

            phone=request.form.get(

                "phone"

            ),

            active=True

        )

        db.session.add(

            representative

        )

        db.session.commit()

        flash(

            "Temsilci başarıyla eklendi.",

            "success"

        )

    except Exception as exc:

        db.session.rollback()

        flash(

            str(

                exc

            ),

            "danger"

        )

    return redirect(

        url_for(

            "representatives.index"

        )

    )


@representatives_bp.route(

    "/edit/<int:id>",

    methods=["POST"]

)
@login_required
def edit(

    id

):

    representative = Representative.query.get_or_404(

        id

    )

    try:

        representative.rep_code = request.form.get(

            "rep_code"

        ).strip()

        representative.ims_code = request.form.get(

            "ims_code"

        ).strip()

        representative.sap_code = request.form.get(

            "sap_code"

        ).strip()

        representative.rep_name = request.form.get(

            "rep_name"

        ).strip()

        representative.region = request.form.get(

            "region"

        )

        representative.city = request.form.get(

            "city"

        )

        representative.district = request.form.get(

            "district"

        )

        representative.territory = request.form.get(

            "territory"

        )

        representative.manager = request.form.get(

            "manager"

        )

        representative.team = request.form.get(

            "team"

        )

        representative.email = request.form.get(

            "email"

        )

        representative.phone = request.form.get(

            "phone"

        )

        db.session.commit()

        flash(

            "Temsilci bilgileri güncellendi.",

            "success"

        )

    except Exception as exc:

        db.session.rollback()

        flash(

            str(

                exc

            ),

            "danger"

        )

    return redirect(

        url_for(

            "representatives.index"

        )

    )

@representatives_bp.route(

    "/status/<int:id>"

)
@login_required
def status(

    id

):

    representative = Representative.query.get_or_404(

        id

    )

    try:

        representative.active = (

            not representative.active

        )

        db.session.commit()

        flash(

            "Temsilci durumu güncellendi.",

            "success"

        )

    except Exception as exc:

        db.session.rollback()

        flash(

            str(

                exc

            ),

            "danger"

        )

    return redirect(

        url_for(

            "representatives.index"

        )

    )


@representatives_bp.route(

    "/view/<int:id>"

)
@login_required
def view(

    id

):

    representative = Representative.query.get_or_404(

        id

    )

    active_period = PeriodService.get_active_period()
    year = request.args.get("year", type=int) or active_period["year"]
    month = request.args.get("month", type=int) or active_period["month"]
    assignments = RepresentativeBrickAssignment.query.filter_by(
        representative_id=id, year=year, month=month, active=True
    ).order_by(RepresentativeBrickAssignment.brick).all() if year and month else []
    targets = Target.query.filter_by(representative_id=id, year=year, month=month).join(Product).order_by(Product.display_order, Product.product_name).all()
    summaries = {
        item.product_id: item
        for item in IMSSummary.query.filter_by(representative_id=id, year=year, month=month).all()
    }
    product_rows, totals = [], {
        "target_tl": 0.0,
        "actual_tl": 0.0,
        "target_unit": 0.0,
        "actual_unit": 0.0,
        "remaining_tl": 0.0,
    }
    for target in targets:
        summary = summaries.get(target.product_id)
        actual_tl = float(summary.tl if summary else 0.0)
        actual_unit = float(summary.unit if summary else 0.0)
        target_tl = float(target.tl_target or 0.0)
        target_unit = float(target.unit_target or 0.0)
        product_rows.append({
            "product": target.product,
            "target_tl": target_tl,
            "actual_tl": actual_tl,
            "target_unit": target_unit,
            "actual_unit": actual_unit,
            "percent": round(actual_tl * 100.0 / target_tl, 1) if target_tl else 0.0,
        })
        totals["target_tl"] += target_tl
        totals["actual_tl"] += actual_tl
        totals["target_unit"] += target_unit
        totals["actual_unit"] += actual_unit
        # One product's over-performance must not hide another product's
        # remaining target. Total realization remains uncapped.
        totals["remaining_tl"] += max(target_tl - actual_tl, 0.0)
    totals = {key: round(value, 2) for key, value in totals.items()}
    totals["percent"] = round(totals["actual_tl"] * 100.0 / totals["target_tl"], 1) if totals["target_tl"] else 0.0
    market_analysis = RepresentativeMarketService(representative, year, month).build()
    annual_realization = AnnualRealizationService.build(year, [representative.id])
    representatives = Representative.query.filter(
        Representative.active.is_(True), _visible_representative_filter()
    ).order_by(Representative.rep_name.asc()).all()
    return render_template(
        "representative_detail.html",
        representative=representative,
        representatives=representatives,
        assignments=assignments,
        products=product_rows,
        totals=totals,
        market_analysis=market_analysis,
        annual_realization=annual_realization,
        year=year,
        month=month,
    )


@representatives_bp.route("/search")
@login_required
def search():
    query = (request.args.get("q") or "").strip()
    if len(query) < 2:
        return jsonify({"results": []})

    active_period = PeriodService.get_active_period()
    normalized_query = _search_key(query)
    all_representatives = Representative.query.order_by(Representative.region.asc(), Representative.city.asc()).all()
    region_matches = [rep for rep in all_representatives if any(
        normalized_query in _search_key(value) for value in (rep.region, rep.city, rep.territory)
    )]
    region_results, seen_regions = [], set()
    for rep in region_matches:
        region_key = (rep.region or rep.city or rep.territory or "").strip()
        if not region_key or region_key in seen_regions:
            continue
        seen_regions.add(region_key)
        region_results.append({
            "kind": "region",
            "title": " ".join(
                part for index, part in enumerate([region_key, rep.city])
                if part and (index == 0 or part != region_key)
            ),
            "meta": "Bölge performansı · Aylık / 3 aylık / 6 aylık / yıllık",
            "url": url_for("regions.detail", region_key=region_key, year=active_period["year"], month=active_period["month"]),
        })
        if len(region_results) >= 4:
            break
    reps = [rep for rep in all_representatives if _representative_display_name(rep.rep_name).casefold() != "genel" and any(
        normalized_query in _search_key(value) for value in (rep.rep_name, rep.rep_code, rep.city)
    )]
    reps.sort(key=lambda rep: (not rep.active, _search_key(rep.rep_name)))
    reps = reps[:7]
    results = region_results + [{
        "kind": "representative",
        "title": _representative_display_name(rep.rep_name),
        "meta": " · ".join(part for part in [rep.region, rep.city, rep.territory] if part) or "Temsilci",
        "url": url_for("representatives.view", id=rep.id, year=active_period["year"], month=active_period["month"]),
    } for rep in reps]

    brick_rows = RepresentativeBrickAssignment.query.join(Representative).filter(
        RepresentativeBrickAssignment.year == active_period["year"],
        RepresentativeBrickAssignment.month == active_period["month"],
        RepresentativeBrickAssignment.active.is_(True),
        _visible_representative_filter(),
        RepresentativeBrickAssignment.brick.ilike(f"%{query}%"),
    ).order_by(RepresentativeBrickAssignment.brick.asc()).limit(7).all()
    known_reps = {item["url"] for item in results}
    for assignment in brick_rows:
        url = url_for("representatives.view", id=assignment.representative_id, year=active_period["year"], month=active_period["month"])
        if url in known_reps:
            continue
        results.append({
            "kind": "brick",
            "title": assignment.brick,
            "meta": f"{_representative_display_name(assignment.representative.rep_name)} · {assignment.territory or assignment.city or 'Brick'}",
            "url": url,
        })
        known_reps.add(url)

    products = [product for product in Product.query.order_by(Product.display_order.asc(), Product.product_name.asc()).all() if any(
        normalized_query in _search_key(value) for value in (product.product_name, product.product_code, product.ims_name)
    )][:5]
    for product in products:
        results.append({
            "kind": "product",
            "title": product.product_name,
            "meta": " · ".join(part for part in [product.product_code, product.category] if part) or "Ürün",
            "url": url_for("products.index"),
        })
    return jsonify({"results": results[:10]})


@representatives_bp.route("/view/<int:id>/assignments", methods=["POST"])
@login_required
def save_assignment(id):
    representative = Representative.query.get_or_404(id)
    try:
        year, month, brick = int(request.form["year"]), int(request.form["month"]), request.form["brick"].strip()
        assignment = RepresentativeBrickAssignment.query.filter_by(
            year=year, month=month, brick=brick, representative_id=representative.id
        ).first()
        if assignment is None:
            assignment = RepresentativeBrickAssignment(year=year, month=month, brick=brick)
            db.session.add(assignment)
        assignment.representative_id, assignment.source, assignment.active = representative.id, "MANUAL", True
        assignment.inactive_reason, assignment.deactivated_at = None, None
        assignment.quarter = f"Q{((month - 1) // 3) + 1}"
        db.session.commit()
        flash("Dönemsel brick ataması kaydedildi.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("representatives.view", id=id, year=request.form.get("year"), month=request.form.get("month")))


def _can_manage_assignments():
    return str(getattr(current_user, "role", "") or "").casefold() in {
        "admin", "administrator", "manager", "yönetici", "yonetici"
    }


@representatives_bp.route("/territory-management")
@login_required
def territory_management():
    active_period = PeriodService.get_active_period()
    year = request.args.get("year", type=int) or active_period["year"]
    month = request.args.get("month", type=int) or active_period["month"]
    representatives = Representative.query.order_by(
        Representative.active.desc(), Representative.region.asc().nullslast(), Representative.rep_name.asc()
    ).all()
    assignments = RepresentativeBrickAssignment.query.filter_by(year=year, month=month).order_by(
        RepresentativeBrickAssignment.active.desc(), RepresentativeBrickAssignment.brick.asc()
    ).all()
    counts = {}
    for item in assignments:
        bucket = counts.setdefault(item.representative_id, {"active": 0, "passive": 0, "total": 0})
        bucket["active" if item.active else "passive"] += 1
        bucket["total"] += 1
    return render_template(
        "territory_management.html", representatives=representatives, assignments=assignments,
        counts=counts, year=year, month=month, can_manage=_can_manage_assignments(),
    )


@representatives_bp.route("/territory-management/<int:assignment_id>/status", methods=["POST"])
@login_required
def territory_status(assignment_id):
    if not _can_manage_assignments():
        flash("Bu işlem için yönetici yetkisi gereklidir.", "danger")
        return redirect(url_for("representatives.territory_management"))
    assignment = RepresentativeBrickAssignment.query.get_or_404(assignment_id)
    make_active = request.form.get("active") == "1"
    assignment.active = make_active
    assignment.source = "MANUAL"
    assignment.inactive_reason = None if make_active else (request.form.get("reason") or "Yönetici tarafından pasife alındı").strip()
    assignment.deactivated_at = None if make_active else datetime.utcnow()
    db.session.commit()
    flash(f"{assignment.brick} çalışma alanı {'aktifleştirildi' if make_active else 'pasife alındı'}.", "success")
    return redirect(url_for("representatives.territory_management", year=assignment.year, month=assignment.month, representative_id=assignment.representative_id))


@representatives_bp.route("/territory-management/<int:assignment_id>/transfer", methods=["POST"])
@login_required
def territory_transfer(assignment_id):
    if not _can_manage_assignments():
        flash("Bu işlem için yönetici yetkisi gereklidir.", "danger")
        return redirect(url_for("representatives.territory_management"))
    assignment = RepresentativeBrickAssignment.query.get_or_404(assignment_id)
    target = Representative.query.get_or_404(request.form.get("target_representative_id", type=int))
    if not target.active or target.id == assignment.representative_id:
        flash("Aktif ve farklı bir hedef temsilci seçilmelidir.", "danger")
        return redirect(url_for("representatives.territory_management", year=assignment.year, month=assignment.month))
    existing = RepresentativeBrickAssignment.query.filter_by(
        year=assignment.year, month=assignment.month, brick=assignment.brick, representative_id=target.id
    ).first()
    if existing is None:
        existing = RepresentativeBrickAssignment(
            representative_id=target.id, year=assignment.year, month=assignment.month,
            quarter=assignment.quarter, brick=assignment.brick, territory=assignment.territory,
            city=assignment.city, source="MANUAL", active=True,
        )
        db.session.add(existing)
    else:
        existing.active, existing.source = True, "MANUAL"
        existing.inactive_reason, existing.deactivated_at = None, None
    assignment.active, assignment.source = False, "MANUAL"
    assignment.inactive_reason = f"{target.rep_name} temsilcisine devredildi"
    assignment.deactivated_at = datetime.utcnow()
    db.session.commit()
    flash(f"{assignment.brick}, {target.rep_name} temsilcisine devredildi.", "success")
    return redirect(url_for("representatives.territory_management", year=assignment.year, month=assignment.month, representative_id=target.id))


@representatives_bp.route(

    "/api"

)
@login_required
def api():

    representatives = Representative.query.order_by(

        Representative.rep_name.asc()

    ).all()

    return jsonify(

        {

            "success": True,

            "count": len(

                representatives

            ),

            "representatives": [

                {

                    "id": representative.id,

                    "rep_code": representative.rep_code,

                    "ims_code": representative.ims_code,

                    "sap_code": representative.sap_code,

                    "rep_name": representative.rep_name,

                    "region": representative.region,

                    "city": representative.city,

                    "district": representative.district,

                    "territory": representative.territory,

                    "manager": representative.manager,

                    "team": representative.team,

                    "email": representative.email,

                    "phone": representative.phone,

                    "active": representative.active

                }

                for representative in representatives

            ]

        }

    )


@representatives_bp.route(

    "/health"

)
@login_required
def health():

    return jsonify(

        {

            "success": True,

            "module": "Representatives",

            "version": "1.0.0",

            "statistics": {

                "total":

                    Representative.query.count(),

                "active":

                    Representative.query.filter_by(

                        active=True

                    ).count(),

                "inactive":

                    Representative.query.filter_by(

                        active=False

                    ).count()

            }

        }

    )
