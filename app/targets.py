from flask import Blueprint
from flask import render_template
from flask import request
from flask import redirect
from flask import url_for
from flask import flash

from flask_login import login_required

from app.extensions import db
from app.models import Target
from app.models import Product
from app.models import Representative

targets_bp = Blueprint(
    "targets",
    __name__,
    url_prefix="/targets"
)


def calculate_quarter(month):

    month = int(month)

    if month <= 3:
        return "Q1"

    if month <= 6:
        return "Q2"

    if month <= 9:
        return "Q3"

    return "Q4"


@targets_bp.route("/")
@login_required
def index():

    targets = Target.query.order_by(
        Target.year.desc(),
        Target.month.desc(),
        Target.id.desc()
    ).all()

    representatives = Representative.query.filter_by(
        active=True
    ).order_by(
        Representative.rep_name
    ).all()

    products = Product.query.filter_by(
        is_active=True
    ).order_by(
        Product.display_order.asc(),
        Product.product_name.asc()
    ).all()

    return render_template(
        "targets.html",
        targets=targets,
        representatives=representatives,
        products=products
    )


@targets_bp.route("/add", methods=["POST"])
@login_required
def add():

    year = int(request.form["year"])

    month = int(request.form["month"])

    representative_id = int(
        request.form["representative"]
    )

    product_id = int(
        request.form["product"]
    )

    quarter = calculate_quarter(month)

    exists = Target.query.filter_by(

        year=year,

        month=month,

        representative_id=representative_id,

        product_id=product_id

    ).first()

    if exists:

        flash(
            "Bu hedef daha önce eklenmiş.",
            "warning"
        )

        return redirect(
            url_for("targets.index")
        )

    target = Target(

        year=year,

        month=month,

        quarter=quarter,

        representative_id=representative_id,

        product_id=product_id,

        unit_target=float(
            request.form.get(
                "unit_target",
                0
            )
        ),

        tl_target=float(
            request.form.get(
                "tl_target",
                0
            )
        )

    )

    db.session.add(target)

    db.session.commit()

    flash(
        "Hedef başarıyla kaydedildi.",
        "success"
    )

    return redirect(
        url_for("targets.index")
    )
