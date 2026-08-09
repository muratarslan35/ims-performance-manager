from flask import Blueprint
from flask import flash
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for

from flask_login import login_required

from app.extensions import db
from app.models import Product, PrimeRule, Setting
from app.services.alias_service import AliasService


PRIME_SETTING_DEFAULTS = {
    "MAIN_PRIME": "50000",
    "CIRO_PRIME": "20000",
    "PRIME_STEP": "5",
    "STEP_AMOUNT": "2500",
    "MAX_PRIME_PERCENT": "140",
    "MIN_PRIME_PERCENT": "100",
    "TOTAL_PERCENT_REQUIRED": "100",
    "ALLOW_CIRO_WITHOUT_PRODUCT": "1",
    "RECOVERY_EFFECT_RATE": "2",
    "QUARTER_EFFECT_RATE": "10",
    "PRODUCT_COEFFICIENT_DEFAULT": "1",
    "PRODUCT_BONUS_RATE": "1",
    "BONUS_RATE": "5",
    "PENALTY_RATE": "3",
    "PENALTY_PER_FAILED_PRODUCT": "1500",
    "WHAT_IF_WORST_FACTOR": "0.85",
    "WHAT_IF_EXPECTED_FACTOR": "1.10",
    "WHAT_IF_BEST_FACTOR": "1.25",
    "SLIDER_MAX_PERCENT": "150",
    "TARGET_75": "75",
    "TARGET_90": "90",
    "TARGET_100": "100",
    "PRIME_PRODUCT_COUNT": "4",
    "REQUIRED_90_COUNT": "3",
    "REQUIRED_75_COUNT": "1",
}


def ensure_prime_settings():
    changed = False
    for key, value in PRIME_SETTING_DEFAULTS.items():
        setting = Setting.query.filter_by(setting_key=key).first()
        if setting:
            continue
        db.session.add(
            Setting(
                setting_key=key,
                setting_value=value,
                description="Sistem Varsayılanı",
            )
        )
        changed = True
    if changed:
        db.session.commit()


settings_bp = Blueprint(

    "settings",

    __name__,

    url_prefix="/settings"

)


@settings_bp.route(

    "/"

)
@login_required
def index():
    ensure_prime_settings()

    settings = Setting.query.order_by(

        Setting.setting_key.asc()

    ).all()

    products = Product.query.order_by(

        Product.display_order.asc(),

        Product.product_name.asc()

    ).all()

    return render_template(

        "settings.html",

        settings=settings,

        products=products

    )


@settings_bp.route(

    "/save",

    methods=["POST"]

)
@login_required
def save():
    try:
        ensure_prime_settings()
        for item in Setting.query.all():

            value = request.form.get(

                item.setting_key

            )

            if value is None:

                continue

            item.setting_value = value

        db.session.commit()

        flash(

            "Ayarlar güncellendi.",

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

            "settings.index"

        )

    )


@settings_bp.route(

    "/api"

)
@login_required
def api():
    ensure_prime_settings()
    settings = Setting.query.order_by(

        Setting.setting_key.asc()

    ).all()

    return jsonify(

        {

            "success": True,

            "count": len(

                settings

            ),

            "settings": [

                {

                    "id": item.id,

                    "key": item.setting_key,

                    "value": item.setting_value,

                    "description": item.description

                }

                for item in settings

            ]

        }

    )


@settings_bp.route(

    "/health"

)
@login_required
def health():

    return jsonify(

        {

            "success": True,

            "module": "Settings",

            "version": "1.0.0",

            "statistics": {

                "total":

                    Setting.query.count()

            }

        }

    )


@settings_bp.route(

    "/reset",

    methods=["POST"]

)
@login_required
def reset():
    try:
        for key, value in PRIME_SETTING_DEFAULTS.items():
            setting = Setting.query.filter_by(
                setting_key=key
            ).first()

            if setting:

                setting.setting_value = value

            else:

                db.session.add(

                    Setting(

                        setting_key=key,

                        setting_value=value,

                        description="Sistem Varsayılanı"

                    )

                )

        db.session.commit()

        flash(

            "Varsayılan ayarlar yüklendi.",

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

            "settings.index"

        )

    )


# ---------------------------------------------------------------------------
# Premium product management
# ---------------------------------------------------------------------------

@settings_bp.route("/products/toggle-prime/<int:product_id>", methods=["POST"])
@login_required
def toggle_prime(product_id):
    """One-click include/exclude a product from the prime calculation."""
    product = Product.query.get_or_404(product_id)
    try:
        product.is_prime_product = not product.is_prime_product
        rule = PrimeRule.query.filter_by(product_id=product.id, active=True).first()
        if rule:
            rule.include_in_prime = product.is_prime_product
        db.session.commit()
        state = "dahil edildi" if product.is_prime_product else "çıkarıldı"
        flash(f"'{product.product_name}' prim hesabına {state}.", "success")
        AliasService.refresh()
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("settings.index"))


@settings_bp.route("/products/update/<int:product_id>", methods=["POST"])
@login_required
def update_product(product_id):
    """Update premium product settings (threshold, TL inclusion)."""
    product = Product.query.get_or_404(product_id)
    try:
        required_percent = request.form.get("required_percent", type=float)
        include_total_tl = request.form.get("include_total_tl") == "1"
        is_active = request.form.get("is_active") == "1"
        if required_percent is not None:
            product.required_percent = required_percent
        product.include_total_tl = include_total_tl
        product.is_active = is_active
        rule = PrimeRule.query.filter_by(product_id=product.id, active=True).first()
        if rule:
            if required_percent is not None:
                rule.required_percent = int(required_percent)
            rule.include_in_total_tl = include_total_tl
        db.session.commit()
        flash(f"'{product.product_name}' ayarları güncellendi.", "success")
        AliasService.refresh()
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("settings.index"))


@settings_bp.route("/products/create", methods=["POST"])
@login_required
def create_product():
    """Create a new product directly from settings."""
    try:
        product_code = request.form.get("product_code", "").strip().upper()
        product_name = request.form.get("product_name", "").strip()
        required_percent = request.form.get("required_percent", type=float, default=0.0)
        is_prime_product = request.form.get("is_prime_product") == "1"
        include_total_tl = request.form.get("include_total_tl") == "1"
        if not product_code or not product_name:
            flash("Ürün kodu ve adı zorunludur.", "warning")
            return redirect(url_for("settings.index"))
        existing = Product.query.filter_by(product_code=product_code).first()
        if existing:
            flash(f"'{product_code}' kodu zaten mevcut.", "warning")
            return redirect(url_for("settings.index"))
        max_order = db.session.query(db.func.max(Product.display_order)).scalar() or 0
        product = Product(
            product_code=product_code,
            product_name=product_name,
            required_percent=required_percent,
            is_prime_product=is_prime_product,
            include_total_tl=include_total_tl,
            display_order=max_order + 1,
            is_active=True,
        )
        db.session.add(product)
        db.session.flush()
        rule = PrimeRule(
            product_id=product.id,
            required_percent=int(required_percent),
            include_in_prime=is_prime_product,
            include_in_total_tl=include_total_tl,
            active=True,
        )
        db.session.add(rule)
        db.session.commit()
        flash(f"'{product_name}' ürünü oluşturuldu.", "success")
        AliasService.refresh()
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("settings.index"))


@settings_bp.route("/products/api")
@login_required
def products_api():
    """Return all products with their prime configuration as JSON."""
    products = Product.query.order_by(Product.display_order.asc()).all()
    return jsonify({
        "success": True,
        "count": len(products),
        "products": [
            {
                "id": p.id,
                "product_code": p.product_code,
                "product_name": p.product_name,
                "is_prime_product": p.is_prime_product,
                "required_percent": p.required_percent,
                "include_total_tl": p.include_total_tl,
                "is_active": p.is_active,
            }
            for p in products
        ],
    })
