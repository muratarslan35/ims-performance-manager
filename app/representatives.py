from flask import Blueprint
from flask import flash
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for

from flask_login import login_required
from sqlalchemy import or_

from app.extensions import db
from app.models import IMSSummary, Product, Representative, RepresentativeBrickAssignment, Target
from app.services.period_service import PeriodService
from app.services.representative_market_service import RepresentativeMarketService


representatives_bp = Blueprint(

    "representatives",

    __name__,

    url_prefix="/representatives"

)


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
        rows = RepresentativeBrickAssignment.query.filter_by(year=latest.year, month=latest.month).order_by(
            RepresentativeBrickAssignment.brick.asc()
        ).all()
        for assignment in rows:
            assignments_by_rep.setdefault(assignment.representative_id, []).append(assignment)

    # The general unassigned placeholder duplicates brick portfolios which are
    # already shown under their regional unassigned representative records.
    representatives = Representative.query.filter(
        ~(
            (Representative.active.is_(False))
            & (Representative.rep_name.ilike("ATANMAMIŞ · GENEL%"))
        )
    ).order_by(
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
    assignments = RepresentativeBrickAssignment.query.filter_by(representative_id=id, year=year, month=month).order_by(RepresentativeBrickAssignment.brick).all() if year and month else []
    targets = Target.query.filter_by(representative_id=id, year=year, month=month).join(Product).order_by(Product.display_order, Product.product_name).all()
    summaries = {
        item.product_id: item
        for item in IMSSummary.query.filter_by(representative_id=id, year=year, month=month).all()
    }
    product_rows, totals = [], {"target_tl": 0.0, "actual_tl": 0.0, "target_unit": 0.0, "actual_unit": 0.0}
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
    totals = {key: round(value, 2) for key, value in totals.items()}
    totals["remaining_tl"] = round(max(totals["target_tl"] - totals["actual_tl"], 0.0), 2)
    totals["percent"] = round(totals["actual_tl"] * 100.0 / totals["target_tl"], 1) if totals["target_tl"] else 0.0
    market_analysis = RepresentativeMarketService(representative, year, month).build()
    representatives = Representative.query.filter_by(active=True).order_by(Representative.rep_name.asc()).all()
    return render_template(
        "representative_detail.html",
        representative=representative,
        representatives=representatives,
        assignments=assignments,
        products=product_rows,
        totals=totals,
        market_analysis=market_analysis,
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
    reps = Representative.query.filter(
        or_(
            Representative.rep_name.ilike(f"%{query}%"),
            Representative.rep_code.ilike(f"%{query}%"),
            Representative.city.ilike(f"%{query}%"),
        )
    ).order_by(Representative.active.desc(), Representative.rep_name.asc()).limit(7).all()
    results = [{
        "kind": "representative",
        "title": rep.rep_name,
        "meta": " · ".join(part for part in [rep.region, rep.city, rep.territory] if part) or "Temsilci",
        "url": url_for("representatives.view", id=rep.id, year=active_period["year"], month=active_period["month"]),
    } for rep in reps]

    brick_rows = RepresentativeBrickAssignment.query.join(Representative).filter(
        RepresentativeBrickAssignment.year == active_period["year"],
        RepresentativeBrickAssignment.month == active_period["month"],
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
            "meta": f"{assignment.representative.rep_name} · {assignment.territory or assignment.city or 'Brick'}",
            "url": url,
        })
        known_reps.add(url)

    products = Product.query.filter(
        or_(
            Product.product_name.ilike(f"%{query}%"),
            Product.product_code.ilike(f"%{query}%"),
            Product.ims_name.ilike(f"%{query}%"),
        )
    ).order_by(Product.display_order.asc(), Product.product_name.asc()).limit(5).all()
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
        assignment.representative_id, assignment.source = representative.id, "MANUAL"
        assignment.quarter = f"Q{((month - 1) // 3) + 1}"
        db.session.commit()
        flash("Dönemsel brick ataması kaydedildi.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("representatives.view", id=id, year=request.form.get("year"), month=request.form.get("month")))


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
