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


@targets_bp.route("/")
@login_required
def index():

    targets = Target.query.order_by(
        Target.year.desc(),
        Target.month.desc()
    ).all()

    representatives = Representative.query.order_by(
        Representative.rep_name
    ).all()

    products = Product.query.order_by(
        Product.product_name
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

    target = Target(

        year=request.form["year"],

        month=request.form["month"],

        quarter=request.form["quarter"],

        representative_id=request.form["representative"],

        product_id=request.form["product"],

        unit_target=request.form["unit_target"],

        tl_target=request.form["tl_target"]

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
