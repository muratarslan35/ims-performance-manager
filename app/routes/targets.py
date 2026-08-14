from flask import Blueprint
from flask import flash
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for
from sqlalchemy import and_

from flask_login import login_required

from app.extensions import db
from app.models import (
    Target,
    Representative,
    Product,
    IMSSummary
)
from app.services.target_box_calculation_service import TargetBoxCalculationService


targets_bp = Blueprint(

    "targets",

    __name__,

    url_prefix="/targets"

)


@targets_bp.route(

    "/"

)
@login_required
def index():

    targets = Target.query.order_by(

        Target.year.desc(),

        Target.month.desc()

    ).all()

    representatives = Representative.query.filter_by(

        active=True

    ).order_by(

        Representative.rep_name.asc()

    ).all()

    products = Product.query.filter_by(

        is_active=True

    ).order_by(

        Product.display_order.asc()

    ).all()

    grouped = {}
    for target in targets:
        group = grouped.setdefault(target.representative_id, {"representative": target.representative, "targets": []})
        group["targets"].append(target)
    target_groups = list(grouped.values())
    for group in target_groups: group["targets"].sort(key=lambda item: (item.product.display_order, item.product.product_name))
    target_groups.sort(key=lambda item: ((item["representative"].region or "999"), item["representative"].city or "", item["representative"].rep_name))

    return render_template(

        "targets.html",

        targets=targets,

        representatives=representatives,

        products=products,
        target_groups=target_groups

    )


@targets_bp.route("/recalculate-box-targets", methods=["POST"])
@login_required
def recalculate_box_targets():
    """Apply TL target / current unit price to every stored target record."""
    try:
        changed = TargetBoxCalculationService.synchronize()
        db.session.commit()
        flash(f"Kutu hedefleri ürün birim fiyatlarına göre güncellendi ({changed} hedef kaydı).", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Kutu hedefi hesaplanamadı: {exc}", "danger")
    return redirect(url_for("targets.index"))

@targets_bp.route("/analysis")
@login_required
def analysis():
    """Executive target-vs-IMS workspace, scoped to a selected period."""
    latest = Target.query.order_by(Target.year.desc(), Target.month.desc()).first()
    year = request.args.get("year", type=int) or (latest.year if latest else None); month = request.args.get("month", type=int) or (latest.month if latest else None)
    region, search = (request.args.get("region") or "").strip(), (request.args.get("q") or "").strip()
    query = db.session.query(Target, Representative, Product, IMSSummary).join(Representative, Representative.id == Target.representative_id).join(Product, Product.id == Target.product_id).outerjoin(IMSSummary, and_(IMSSummary.representative_id == Target.representative_id, IMSSummary.product_id == Target.product_id, IMSSummary.year == Target.year, IMSSummary.month == Target.month))
    if year: query = query.filter(Target.year == year)
    if month: query = query.filter(Target.month == month)
    if region: query = query.filter(Representative.region == region)
    if search: query = query.filter(Representative.rep_name.ilike(f"%{search}%"))
    rows = query.order_by(Representative.region.asc(), Representative.city.asc(), Representative.rep_name.asc(), Product.display_order.asc()).all()
    details, totals = [], {"unit_target": 0.0, "unit_actual": 0.0, "tl_target": 0.0, "tl_actual": 0.0}
    for target, representative, product, summary in rows:
        unit_actual, tl_actual = float(summary.unit or 0) if summary else 0.0, float(summary.tl or 0) if summary else 0.0
        unit_target = float(round(float(target.unit_target or 0) or (float(target.tl_target or 0) / float(product.unit_price or 1))))
        details.append({"target": target, "representative": representative, "product": product, "unit_target": unit_target, "unit_actual": unit_actual, "tl_actual": tl_actual, "unit_percent": round(unit_actual * 100 / unit_target, 1) if unit_target else 0.0, "tl_percent": round(tl_actual * 100 / target.tl_target, 1) if target.tl_target else 0.0})
        totals["unit_target"] += unit_target; totals["unit_actual"] += unit_actual; totals["tl_target"] += float(target.tl_target or 0); totals["tl_actual"] += tl_actual
    totals["unit_percent"] = round(totals["unit_actual"] * 100 / totals["unit_target"], 1) if totals["unit_target"] else 0.0; totals["tl_percent"] = round(totals["tl_actual"] * 100 / totals["tl_target"], 1) if totals["tl_target"] else 0.0
    detail_groups = []
    for item in details:
        if not detail_groups or detail_groups[-1]["representative"].id != item["representative"].id:
            detail_groups.append({"representative": item["representative"], "items": []})
        detail_groups[-1]["items"].append(item)
    periods = db.session.query(Target.year, Target.month).distinct().order_by(Target.year.desc(), Target.month.desc()).all(); regions = db.session.query(Representative.region, Representative.city).filter(Representative.region.isnot(None)).distinct().order_by(Representative.region, Representative.city).all()
    return render_template("targets_analysis.html", details=details, detail_groups=detail_groups, totals=totals, year=year, month=month, region=region, search=search, periods=periods, regions=regions)


@targets_bp.route(

    "/add",

    methods=["POST"]

)
@login_required
def add():

    try:

        target = Target(

            representative_id=int(

                request.form.get(

                    "representative_id"

                )

            ),

            product_id=int(

                request.form.get(

                    "product_id"

                )

            ),

            year=int(

                request.form.get(

                    "year"

                )

            ),

            month=int(

                request.form.get(

                    "month"

                )

            ),

            target_unit=float(

                request.form.get(

                    "target_unit",

                    0

                ) or 0

            ),

            target_tl=float(

                request.form.get(

                    "target_tl",

                    0

                ) or 0

            )

        )

        db.session.add(

            target

        )

        db.session.commit()

        flash(

            "Hedef başarıyla eklendi.",

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

            "targets.index"

        )

    )


@targets_bp.route(

    "/edit/<int:id>",

    methods=["POST"]

)
@login_required
def edit(

    id

):

    target = Target.query.get_or_404(

        id

    )

    try:

        target.target_unit = float(

            request.form.get(

                "target_unit",

                0

            ) or 0

        )

        target.target_tl = float(

            request.form.get(

                "target_tl",

                0

            ) or 0

        )

        db.session.commit()

        flash(

            "Hedef güncellendi.",

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

            "targets.index"

        )

    )

@targets_bp.route(

    "/delete/<int:id>",

    methods=["POST"]

)
@login_required
def delete(

    id

):

    target = Target.query.get_or_404(

        id

    )

    try:

        db.session.delete(

            target

        )

        db.session.commit()

        flash(

            "Hedef silindi.",

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

            "targets.index"

        )

    )


@targets_bp.route(

    "/view/<int:id>"

)
@login_required
def view(

    id

):

    target = Target.query.get_or_404(

        id

    )

    return render_template(

        "target_detail.html",

        target=target

    )


@targets_bp.route(

    "/api"

)
@login_required
def api():

    targets = Target.query.order_by(

        Target.year.desc(),

        Target.month.desc()

    ).all()

    return jsonify(

        {

            "success": True,

            "count": len(

                targets

            ),

            "targets": [

                {

                    "id": target.id,

                    "representative_id": target.representative_id,

                    "product_id": target.product_id,

                    "year": target.year,

                    "month": target.month,

                    "target_unit": target.target_unit,

                    "target_tl": target.target_tl

                }

                for target in targets

            ]

        }

    )


@targets_bp.route(

    "/health"

)
@login_required
def health():

    return jsonify(

        {

            "success": True,

            "module": "Targets",

            "version": "1.0.0",

            "statistics": {

                "total":

                    Target.query.count(),

                "representatives":

                    Representative.query.filter_by(

                        active=True

                    ).count(),

                "products":

                    Product.query.filter_by(

                        is_active=True

                    ).count()

            }

        }

    )
