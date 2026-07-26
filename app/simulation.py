from flask import Blueprint
from flask import jsonify
from flask import render_template
from flask import request

from flask_login import login_required

from app.models import (
    Representative,
    Product
)

from app.services.simulation_service import (
    SimulationService
)


simulation_bp = Blueprint(

    "simulation",

    __name__,

    url_prefix="/simulation"

)


def build_overrides(

    data

):

    overrides = {}

    duplicates = []

    seen = set()

    for item in data.get(

        "products",

        []

    ):

        product_id = int(

            item.get(

                "product_id",

                0

            )

        )

        if product_id <= 0:

            continue

        if product_id in seen:

            duplicates.append(

                product_id

            )

            continue

        seen.add(

            product_id

        )

        unit = max(

            0,

            float(

                item.get(

                    "unit",

                    0

                )

            )

        )

        tl = max(

            0,

            float(

                item.get(

                    "tl",

                    0

                )

            )

        )

        overrides[product_id] = {

            "unit": unit,

            "tl": tl

        }

    return overrides, duplicates


@simulation_bp.route(

    "/",

    methods=["GET"]

)
@login_required
def index():

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

    return render_template(

        "simulation.html",

        representatives=representatives,

        products=products

    )


@simulation_bp.route(

    "/calculate",

    methods=["POST"]

)
@login_required
def calculate():

    try:

        data = request.get_json() or {}

        representative_id = int(

            data.get(

                "representative_id",

                0

            )

        )

        year = int(

            data.get(

                "year",

                0

            )

        )

        month = int(

            data.get(

                "month",

                0

            )

        )

        if representative_id <= 0:

            return jsonify(

                {

                    "success": False,

                    "message": "Temsilci seçiniz."

                }

            ), 400

        if year <= 0:

            return jsonify(

                {

                    "success": False,

                    "message": "Yıl bilgisi eksik."

                }

            ), 400

        if month < 1 or month > 12:

            return jsonify(

                {

                    "success": False,

                    "message": "Geçersiz ay."

                }

            ), 400

        overrides, duplicates = build_overrides(

            data

        )

        if duplicates:

            return jsonify(

                {

                    "success": False,

                    "message":

                        "Aynı ürün birden fazla gönderildi.",

                    "duplicates":

                        duplicates

                }

            ), 400

        service = SimulationService(

            representative_id=representative_id,

            year=year,

            month=month,

            overrides=overrides

        )

        return jsonify(

            service.report()

        )

    except Exception as exc:

        return jsonify(

            {

                "success": False,

                "message": str(

                    exc

                )

            }

        ), 500


@simulation_bp.route(

    "/product/<int:product_id>"

)
@login_required
def product_info(

    product_id

):

    product = Product.query.get_or_404(

        product_id

    )

    return jsonify(

        {

            "id": product.id,

            "code": product.product_code,

            "name": product.product_name,

            "unit_price": product.unit_price,

            "required_percent": product.required_percent,

            "include_total_tl": product.include_total_tl,

            "active": product.is_active,

            "display_order": product.display_order,

            "prime_product": product.is_prime_product,

            "category": product.category,

            "molecule": product.molecule,

            "strength": product.strength,

            "dosage_form": product.dosage_form

        }

    )


@simulation_bp.route(

    "/representative/<int:rep_id>"

)
@login_required
def representative_info(

    rep_id

):

    representative = Representative.query.get_or_404(

        rep_id

    )

    return jsonify(

        {

            "id": representative.id,

            "code": representative.rep_code,

            "ims_code": representative.ims_code,

            "name": representative.rep_name,

            "manager": representative.manager,

            "region": representative.region,

            "city": representative.city,

            "territory": representative.territory,

            "team": representative.team,

            "email": representative.email,

            "phone": representative.phone,

            "active": representative.active

        }

    )


@simulation_bp.route(

    "/health"

)
@login_required
def health():

    return jsonify(

        {

            "success": True,

            "module": "Simulation",

            "service": SimulationService.health(),

            "capabilities": SimulationService.capabilities()

        }

    )


@simulation_bp.route(

    "/validate",

    methods=["POST"]

)
@login_required
def validate():

    data = request.get_json() or {}

    errors = []

    representative_id = int(

        data.get(

            "representative_id",

            0

        )

    )

    year = int(

        data.get(

            "year",

            0

        )

    )

    month = int(

        data.get(

            "month",

            0

        )

    )

    if representative_id <= 0:

        errors.append(

            "Temsilci seçilmedi."

        )

    elif Representative.query.get(

        representative_id

    ) is None:

        errors.append(

            "Temsilci bulunamadı."

        )

    if year <= 0:

        errors.append(

            "Geçersiz yıl."

        )

    if month < 1 or month > 12:

        errors.append(

            "Geçersiz ay."

        )

    overrides, duplicates = build_overrides(

        data

    )

    if duplicates:

        errors.append(

            "Aynı ürün birden fazla gönderildi."

        )

    for product_id in overrides.keys():

        if Product.query.get(

            product_id

        ) is None:

            errors.append(

                f"Ürün bulunamadı ({product_id})"

            )

    return jsonify(

        {

            "success":

                len(

                    errors

                ) == 0,

            "errors":

                errors,

            "override_count":

                len(

                    overrides

                )

        }

    )
