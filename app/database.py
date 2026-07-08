
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import Setting, User


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
}


def initialize_database():
    db.create_all()
    create_default_settings()
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
                    setting_value=value
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
        password=generate_password_hash("Admin12345"),
        role="Admin",
        active=True
    )

    db.session.add(admin)
    db.session.commit()
