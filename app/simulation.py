from flask import Blueprint
from flask import jsonify
from flask import render_template
from flask import request

from flask_login import login_required

from app.models import (
    Representative,
    Product
)

from app.engines.prime_engine import PrimeEngine
from app.engines.quarter_engine import QuarterEngine
from app.engines.recovery_engine import RecoveryEngine


simulation_bp = Blueprint(

    "simulation",

    __name__,

    url_prefix="/simulation"

)


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

        quarter = (

            (month - 1) // 3

        ) + 1

        overrides = {}

        duplicate_products = set()

        products = data.get(

            "products",

            []

        )

        for item in products:

            product_id = int(

                item.get(

                    "product_id",

                    0

                )

            )

            if product_id <= 0:

                continue

            if product_id in overrides:

                duplicate_products.add(

                    product_id

                )

                continue

            unit = float(

                item.get(

                    "unit",

                    0

                )

            )

            tl = float(

                item.get(

                    "tl",

                    0

                )

            )

            if unit < 0:

                unit = 0

            if tl < 0:

                tl = 0

            overrides[product_id] = {

                "unit": unit,

                "tl": tl

            }

        if duplicate_products:

            return jsonify(

                {

                    "success": False,

                    "message":

                        "Aynı ürün birden fazla gönderildi.",

                    "duplicates":

                        list(

                            duplicate_products

                        )

                }

            ), 400

        prime = PrimeEngine(

            representative_id,

            year,

            month,

            overrides=overrides

        )

        quarter_engine = QuarterEngine(

            representative_id,

            year,

            quarter,

            overrides=overrides

        )

        recovery = RecoveryEngine(

            representative_id,

            year,

            quarter,

            overrides=overrides

        )

        prime_result = prime.calculate()

        quarter_result = quarter_engine.calculate()

        recovery_result = recovery.run()

        risk_products = len(

            [

                item

                for item in recovery_result

                if item["status"] != "Tamamlandı"

            ]

        )

        ai_messages = []

        if prime_result["failed_products"]:

            for item in prime_result["failed_products"]:

                ai_messages.append(

                    f'{item["product"]} ürünü %{item["required"]} hedefine ulaşamadı.'

                )

        if risk_products > 0:

            ai_messages.append(

                f"{risk_products} ürün için Q riski devam ediyor."

            )

        if prime_result["main_prime"] == 0:

            ai_messages.append(

                "Ana prim henüz oluşmadı."

            )

        if prime_result["ciro_prime"] == 0:

            ai_messages.append(

                "Ciro primi oluşmadı."

            )

        summary = {

            "monthly_percent":

                prime_result[

                    "total_tl_percent"

                ],

            "quarter_percent":

                quarter_result[

                    "total_percent"

                ],

            "main_prime":

                prime_result[

                    "main_prime"

                ],

            "ciro_prime":

                prime_result[

                    "ciro_prime"

                ],

            "total_prime":

                prime_result[

                    "total_prime"

                ],

            "status":

                prime_result[

                    "status"

                ],

            "completed_products":

                quarter_result[

                    "completed_products"

                ],

            "failed_products":

                quarter_result[

                    "failed_products"

                ],

            "risk_products":

                risk_products,

            "simulation":

                bool(

                    overrides

                ),

            "quarter":

                quarter,

            "month":

                month,

            "year":

                year,

            "ai_messages":

                ai_messages

        }

        return jsonify(

            {

                "success": True,

                "summary": summary,

                "prime": prime_result,

                "quarter": quarter_result,

                "recovery": recovery_result

            }

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

            "version": "1.1.0",

            "prime_engine": True,

            "quarter_engine": True,

            "recovery_engine": True,

            "simulation_enabled": True,

            "features": {

                "override": True,

                "monthly_prime": True,

                "quarter_calculation": True,

                "recovery": True,

                "carry_over": True,

                "risk_score": True,

                "ai_messages": True,

                "auto_quarter": True

            }

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

    if not data.get(

        "representative_id"

    ):

        errors.append(

            "Temsilci seçilmedi."

        )

    if not data.get(

        "year"

    ):

        errors.append(

            "Yıl seçilmedi."

        )

    month = int(

        data.get(

            "month",

            0

        )

    )

    if month < 1 or month > 12:

        errors.append(

            "Geçersiz ay."

        )

    seen = set()

    for item in data.get(

        "products",

        []

    ):

        pid = int(

            item.get(

                "product_id",

                0

            )

        )

        if pid <= 0:

            continue

        if pid in seen:

            errors.append(

                f"Aynı ürün iki kez gönderildi ({pid})"

            )

        seen.add(

            pid

        )

        if float(

            item.get(

                "unit",

                0

            )

        ) < 0:

            errors.append(

                f"Negatif kutu değeri ({pid})"

            )

        if float(

            item.get(

                "tl",

                0

            )

        ) < 0:

            errors.append(

                f"Negatif TL değeri ({pid})"

            )

    return jsonify(

        {

            "success":

                len(

                    errors

                ) == 0,

            "errors":

                errors

        }

    )
