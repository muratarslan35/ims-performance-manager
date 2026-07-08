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
        Product.display_order.asc(),
        Product.product_name.asc()
    ).all()

    return render_template(
        "products.html",
        products=products
    )


@products_bp.route("/add", methods=["POST"])
@login_required
def add():

    product = Product(

        product_code=request.form.get("product_code"),

        product_name=request.form.get("product_name"),

        ims_name=request.form.get("ims_name"),

        category=request.form.get("category"),

        unit_price=float(
            request.form.get("unit_price") or 0
        ),

        is_prime_product=bool(
            request.form.get("prime")
        ),

        display_order=int(
            request.form.get("display_order") or 0
        ),

        is_active=True

    )

    db.session.add(product)

    db.session.commit()

    flash(
        "Ürün başarıyla eklendi.",
        "success"
    )

    return redirect(
        url_for("products.index")
    )


@products_bp.route("/status/<int:id>")
@login_required
def change_status(id):

    product = Product.query.get_or_404(id)

    product.is_active = not product.is_active

    db.session.commit()

    if product.is_active:

        flash(
            "Ürün aktif hale getirildi.",
            "success"
        )

    else:

        flash(
            "Ürün pasif hale getirildi.",
            "warning"
        )

    return redirect(
        url_for("products.index")
    )


@products_bp.route("/prime/<int:id>")
@login_required
def change_prime(id):

    product = Product.query.get_or_404(id)

    product.is_prime_product = (
        not product.is_prime_product
    )

    db.session.commit()

    if product.is_prime_product:

        flash(
            "Ürün Prime ürün olarak işaretlendi.",
            "success"
        )

    else:

        flash(
            "Ürün Prime listesinden çıkarıldı.",
            "warning"
        )

    return redirect(
        url_for("products.index")
    )


@products_bp.route("/edit/<int:id>", methods=["POST"])
@login_required
def edit(id):

    product = Product.query.get_or_404(id)

    product.product_code = request.form.get(
        "product_code"
    )

    product.product_name = request.form.get(
        "product_name"
    )

    product.ims_name = request.form.get(
        "ims_name"
    )

    product.category = request.form.get(
        "category"
    )

    product.unit_price = float(
        request.form.get("unit_price") or 0
    )

    product.display_order = int(
        request.form.get("display_order") or 0
    )

    db.session.commit()

    flash(
        "Ürün bilgileri güncellendi.",
        "success"
    )

    return redirect(
        url_for("products.index")
    )
