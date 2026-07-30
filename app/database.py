import logging

from sqlalchemy import inspect
from werkzeug.security import generate_password_hash
from flask import current_app
from flask import has_app_context

from app.extensions import db

from app.models import (
    Product,
    PrimeRule,
    Setting,
    User
)


DEFAULT_SETTINGS = {

    "MAIN_PRIME": "50000",

    "CIRO_PRIME": "20000",

    "PRIME_STEP": "5",

    "STEP_AMOUNT": "2500",

    "MAX_PRIME_PERCENT": "140",

    "MIN_PRIME_PERCENT": "100",

    "TARGET_75": "75",

    "TARGET_90": "90",

    "TARGET_100": "100",

    "PRIME_PRODUCT_COUNT": "4",

    "REQUIRED_90_COUNT": "3",

    "REQUIRED_75_COUNT": "1",

    "TOTAL_PERCENT_REQUIRED": "100",

    "ALLOW_CIRO_WITHOUT_PRODUCT": "1",

    "ROUNDING": "2"

}


DEFAULT_PRODUCTS = [

    {

        "product_code": "TRAVAZOL",

        "product_name": "Travazol",

        "display_order": 1,

        "is_prime_product": True,

        "required_percent": 90,

        "include_total_tl": True

    },

    {

        "product_code": "MONUROL",

        "product_name": "Monurol",

        "display_order": 2,

        "is_prime_product": True,

        "required_percent": 90,

        "include_total_tl": True

    },

    {

        "product_code": "MIXOVUL",

        "product_name": "Mixovul",

        "display_order": 3,

        "is_prime_product": True,

        "required_percent": 90,

        "include_total_tl": True

    },

    {

        "product_code": "ACNEMIX",

        "product_name": "Acnemix",

        "display_order": 4,

        "is_prime_product": True,

        "required_percent": 75,

        "include_total_tl": True

    },

    {

        "product_code": "STIDERM",

        "product_name": "Stiderm",

        "display_order": 5,

        "is_prime_product": False,

        "required_percent": 0,

        "include_total_tl": True

    },

    {

        "product_code": "BRIMODER",

        "product_name": "Brimoder",

        "display_order": 6,

        "is_prime_product": False,

        "required_percent": 0,

        "include_total_tl": True

    }

]


logger = logging.getLogger(__name__)


def initialize_database():
    inspector = inspect(db.engine)
    required_tables = {"settings", "products", "prime_rules", "users"}
    existing_tables = set(inspector.get_table_names())
    missing_tables = sorted(required_tables - existing_tables)
    if missing_tables:
        message = (
            "Database schema is incomplete; missing required tables: "
            f"{', '.join(missing_tables)}. "
            "Apply Alembic migrations before starting writable traffic."
        )
        strict_schema_check = False
        if has_app_context():
            strict_schema_check = bool(
                current_app.config.get("STRICT_SCHEMA_VALIDATION", False)
            )
        if strict_schema_check:
            logger.error(message)
            raise RuntimeError(message)

        logger.warning(message)
        return

    create_default_settings()

    create_default_products()

    create_default_prime_rules()

    create_admin_user()

def create_default_settings():

    changed = False

    for key, value in DEFAULT_SETTINGS.items():

        setting = Setting.query.filter_by(

            setting_key=key

        ).first()

        if setting is None:

            db.session.add(

                Setting(

                    setting_key=key,

                    setting_value=value,

                    category="Prim",

                    description=key

                )

            )

            changed = True

    if changed:

        db.session.commit()


def create_default_products():

    changed = False

    for item in DEFAULT_PRODUCTS:

        product = Product.query.filter_by(

            product_code=item["product_code"]

        ).first()

        if product:

            continue

        db.session.add(

            Product(

                product_code=item["product_code"],

                product_name=item["product_name"],

                display_order=item["display_order"],

                is_prime_product=item["is_prime_product"],

                required_percent=item["required_percent"],

                include_total_tl=item["include_total_tl"],

                is_active=True

            )

        )

        changed = True

    if changed:

        db.session.commit()


def create_default_prime_rules():

    changed = False

    products = Product.query.all()

    for product in products:

        rule = PrimeRule.query.filter_by(

            product_id=product.id

        ).first()

        if rule:

            continue

        db.session.add(

            PrimeRule(

                product_id=product.id,

                required_percent=product.required_percent,

                include_in_prime=product.is_prime_product,

                include_in_total_tl=product.include_total_tl,

                active=True

            )

        )

        changed = True

    if changed:

        db.session.commit()


def create_admin_user():

    admin = User.query.filter_by(

        email="admin@ipm.local"

    ).first()

    if admin:

        return

    admin = User(

        full_name="Sistem Yöneticisi",

        email="admin@ipm.local",

        password=generate_password_hash(

            "Admin12345"

        ),

        role="Admin",

        active=True

    )

    db.session.add(

        admin

    )

    db.session.commit()
