from flask import Blueprint
from flask import render_template
from flask import request
from flask import redirect
from flask import url_for
from flask import flash

from flask_login import login_required

from app.extensions import db
from app.models import Product

products_bp = Blueprint(
    "products",
    __name__,
    url_prefix="/products"
)


@products_bp.route("/")
@login_required
def index():

    products = Product.query.order_by(
        Product.product_name.asc()
    ).all()

    return render_template(
        "products.html",
        products=products
    )


@products_bp.route("/add", methods=["POST"])
@login_required
def add():

    product_name = request.form.get("product_name")

    category = request.form.get("category")

    prime = request.form.get("prime")

    product = Product(

        product_name=product_name,

        category=category,

        prime_product=True if prime else False

    )

    db.session.add(product)

    db.session.commit()

    flash(

        "Product added successfully.",

        "success"

    )

    return redirect(
        url_for("products.index")
    )


@products_bp.route("/delete/<int:id>")
@login_required
def delete(id):

    product = Product.query.get_or_404(id)

    db.session.delete(product)

    db.session.commit()

    flash(

        "Product deleted.",

        "success"

    )

    return redirect(
        url_for("products.index")
    )
