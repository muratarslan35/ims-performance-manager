from flask import Blueprint
from flask import flash
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for
from flask import jsonify

from flask_login import login_required

from app.extensions import db
from app.models import Product


products_bp = Blueprint(

    "products",

    __name__,

    url_prefix="/products"

)


@products_bp.route(

    "/"

)
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


@products_bp.route(

    "/add",

    methods=["POST"]

)
@login_required
def add():

    try:

        product_name = (request.form.get("product_name") or "").strip()

        product = Product(

            product_code=request.form.get(

                "product_code"

            ).strip(),

            product_name=product_name,

            # IMS adı yönetim ekranından kaldırıldı. Eşleştirme motorunun
            # geriye dönük çalışması için yeni kayıtta ürün adı kullanılır.
            ims_name=product_name,

            category=None,

            molecule=request.form.get(

                "molecule"

            ),

            strength=request.form.get(

                "strength"

            ),

            dosage_form=request.form.get(

                "dosage_form"

            ),

            unit_price=float(

                request.form.get(

                    "unit_price",

                    0

                ) or 0

            ),

            required_percent=0.0,

            include_total_tl=bool(

                request.form.get(

                    "include_total_tl"

                )

            ),

            is_prime_product=bool(

                request.form.get(

                    "prime"

                )

            ),

            display_order=int(

                request.form.get(

                    "display_order",

                    0

                ) or 0

            ),

            is_active=True

        )

        db.session.add(

            product

        )

        db.session.commit()

        flash(

            "Ürün başarıyla eklendi.",

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

            "products.index"

        )

    )


@products_bp.route(

    "/edit/<int:id>",

    methods=["POST"]

)
@login_required
def edit(

    id

):

    product = Product.query.get_or_404(

        id

    )

    try:

        product.product_code = request.form.get(

            "product_code"

        ).strip()

        product.product_name = request.form.get(

            "product_name"

        ).strip()

        # Arayüzden kaldırılan eski alanlar mevcut kayıtlarda korunur.
        if "ims_name" in request.form:
            product.ims_name = (request.form.get("ims_name") or product.product_name).strip()

        if "category" in request.form:
            product.category = request.form.get("category") or None

        product.molecule = request.form.get(

            "molecule"

        )

        product.strength = request.form.get(

            "strength"

        )

        product.dosage_form = request.form.get(

            "dosage_form"

        )

        product.unit_price = float(

            request.form.get(

                "unit_price",

                0

            ) or 0

        )

        if "required_percent" in request.form:
            product.required_percent = float(request.form.get("required_percent") or 0)

        product.include_total_tl = bool(

            request.form.get(

                "include_total_tl"

            )

        )

        product.display_order = int(

            request.form.get(

                "display_order",

                0

            ) or 0

        )

        db.session.commit()

        flash(

            "Ürün bilgileri güncellendi.",

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

            "products.index"

        )

    )


@products_bp.route(

    "/delete/<int:id>",

    methods=["POST"]

)
@login_required
def delete(

    id

):

    product = Product.query.get_or_404(

        id

    )

    try:

        db.session.delete(

            product

        )

        db.session.commit()

        flash(

            "Ürün silindi.",

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

            "products.index"

        )

        )

@products_bp.route(

    "/status/<int:id>"

)
@login_required
def change_status(

    id

):

    product = Product.query.get_or_404(

        id

    )

    try:

        product.is_active = (

            not product.is_active

        )

        db.session.commit()

        flash(

            "Ürün durumu güncellendi.",

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

            "products.index"

        )

    )


@products_bp.route(

    "/prime/<int:id>"

)
@login_required
def change_prime(

    id

):

    product = Product.query.get_or_404(

        id

    )

    try:

        product.is_prime_product = (

            not product.is_prime_product

        )

        db.session.commit()

        flash(

            "Prime durumu güncellendi.",

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

            "products.index"

        )

    )


@products_bp.route(

    "/view/<int:id>"

)
@login_required
def view(

    id

):

    product = Product.query.get_or_404(

        id

    )

    return render_template(

        "product_detail.html",

        product=product

    )


@products_bp.route(

    "/api"

)
@login_required
def api():

    products = Product.query.order_by(

        Product.display_order.asc(),

        Product.product_name.asc()

    ).all()

    return jsonify(

        {

            "success": True,

            "count": len(

                products

            ),

            "products": [

                {

                    "id": product.id,

                    "product_code": product.product_code,

                    "product_name": product.product_name,

                    "ims_name": product.ims_name,

                    "category": product.category,

                    "molecule": product.molecule,

                    "strength": product.strength,

                    "dosage_form": product.dosage_form,

                    "unit_price": product.unit_price,

                    "required_percent": product.required_percent,

                    "include_total_tl": product.include_total_tl,

                    "is_prime_product": product.is_prime_product,

                    "is_active": product.is_active,

                    "display_order": product.display_order

                }

                for product in products

            ]

        }

    )


@products_bp.route(

    "/health"

)
@login_required
def health():

    return jsonify(

        {

            "success": True,

            "module": "Products",

            "version": "1.0.0",

            "statistics": {

                "total":

                    Product.query.count(),

                "active":

                    Product.query.filter_by(

                        is_active=True

                    ).count(),

                "inactive":

                    Product.query.filter_by(

                        is_active=False

                    ).count(),

                "prime":

                    Product.query.filter_by(

                        is_prime_product=True

                    ).count()

            }

        }

    )
