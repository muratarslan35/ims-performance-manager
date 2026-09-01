import os
import tempfile
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

MIGRATIONS_DIR = str(Path(__file__).resolve().parents[1] / "migrations")


@pytest.fixture()
def app():
    os.environ.setdefault("APP_ENV", "development")
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "manager-module.db"

    class TestConfig:
        TESTING = True
        SECRET_KEY = "manager-module-test"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        LOGIN_DISABLED = False
        UPLOAD_FOLDER = Path(temp_dir.name) / "uploads"
        REPORT_FOLDER = Path(temp_dir.name) / "reports"
        BACKUP_FOLDER = Path(temp_dir.name) / "backups"
        LOG_FOLDER = Path(temp_dir.name) / "logs"
        TEMP_FOLDER = Path(temp_dir.name) / "temp"

    from app import create_app
    application = create_app(TestConfig)

    with application.app_context():
        from flask_migrate import upgrade
        from app.database import initialize_database
        from app.extensions import db
        from app.models import Representative, User
        from app.region_manager import RegionManagerScope

        upgrade(directory=MIGRATIONS_DIR)
        initialize_database()
        db.session.add_all([
            Representative(rep_code="R101", rep_name="101 REP", region="101 ADANA", city="ADANA", active=True),
            Representative(rep_code="R201", rep_name="201 REP", region="201 ANKARA", city="ANKARA", active=True),
        ])
        db.session.flush()

        users = {}
        for kind, email in (
            ("region", "region.manager@example.com"),
            ("promotion", "promotion.manager@example.com"),
            ("product", "product.manager@example.com"),
            ("marketing", "marketing.manager@example.com"),
        ):
            user = User(
                full_name=f"{kind.title()} Manager",
                email=email,
                password=generate_password_hash("password123"),
                role="Manager",
                active=True,
            )
            db.session.add(user)
            db.session.flush()
            db.session.add(
                RegionManagerScope(
                    user_id=user.id,
                    manager_type=kind,
                    region_code="101" if kind == "region" else None,
                )
            )
            users[kind] = user.id
        db.session.commit()
        application.config["MANAGER_IDS"] = users

    yield application
    with application.app_context():
        from app.extensions import db
        db.session.remove()
    temp_dir.cleanup()


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, email, password="password123"):
    return client.post(
        "/login",
        data={"email": email, "password": password, "portal": "manager"},
        follow_redirects=False,
    )


def test_manager_type_contract(app):
    from app.extensions import db
    from app.models import User
    from app.region_manager import (
        assigned_region,
        can_access_settings,
        can_manage_managers,
        is_functional_manager,
        is_regional_manager,
        manager_type,
    )

    with app.app_context():
        region = User.query.filter_by(email="region.manager@example.com").one()
        promotion = User.query.filter_by(email="promotion.manager@example.com").one()
        product = User.query.filter_by(email="product.manager@example.com").one()
        marketing = User.query.filter_by(email="marketing.manager@example.com").one()
        admin = User.query.filter_by(email="admin@ipm.local").one()

        assert is_regional_manager(region)
        assert assigned_region(region) == "101"
        assert manager_type(promotion) == "promotion" and is_functional_manager(promotion)
        assert manager_type(product) == "product" and is_functional_manager(product)
        assert manager_type(marketing) == "marketing" and is_functional_manager(marketing)
        assert can_manage_managers(admin)
        assert can_manage_managers(promotion)
        assert not can_manage_managers(product)
        assert can_manage_managers(marketing)
        assert not can_manage_managers(region)
        assert can_access_settings(admin)
        assert not can_access_settings(promotion)
        assert not can_access_settings(product)
        assert not can_access_settings(marketing)
        assert not can_access_settings(region)
        db.session.remove()


@pytest.mark.parametrize("email", [
    "region.manager@example.com",
    "promotion.manager@example.com",
    "product.manager@example.com",
    "marketing.manager@example.com",
])
def test_all_managers_can_view_manager_module(client, email):
    login(client, email)
    response = client.get("/manager-users/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Yönetici Modülü" in html
    assert "Kayıtlı Yöneticiler" in html


@pytest.mark.parametrize("email", ["region.manager@example.com", "product.manager@example.com"])
def test_region_and_product_managers_cannot_create_users(app, client, email):
    login(client, email)
    response = client.post(
        "/manager-users/create",
        data={
            "full_name": "Yetkisiz Yeni Müdür",
            "email": "forbidden.manager@example.com",
            "password": "password123",
            "manager_type": "marketing",
        },
        follow_redirects=True,
    )
    assert "yönetici ekleme veya düzenleme yetkisine sahip değildir" in response.get_data(as_text=True)
    with app.app_context():
        from app.models import User
        assert User.query.filter_by(email="forbidden.manager@example.com").count() == 0


@pytest.mark.parametrize("email", ["promotion.manager@example.com", "marketing.manager@example.com"])
def test_promotion_and_marketing_managers_can_create_users(app, client, email):
    login(client, email)
    new_email = "created." + email
    response = client.post(
        "/manager-users/create",
        data={
            "full_name": "Yeni Ürün Müdürü",
            "email": new_email,
            "password": "password123",
            "manager_type": "product",
            "region_code": "201",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    with app.app_context():
        from app.models import User
        from app.region_manager import RegionManagerScope
        user = User.query.filter_by(email=new_email).one()
        scope = RegionManagerScope.query.filter_by(user_id=user.id).one()
        assert scope.manager_type == "product"
        assert scope.region_code is None


@pytest.mark.parametrize("email", [
    "promotion.manager@example.com",
    "product.manager@example.com",
    "marketing.manager@example.com",
])
def test_functional_managers_cannot_open_settings_but_keep_operational_navigation(client, email):
    login(client, email)
    denied = client.get("/settings/", follow_redirects=True)
    assert denied.status_code == 200
    assert "Ayarlar menüsüne erişemezsiniz" in denied.get_data(as_text=True)

    dashboard = client.get("/dashboard/")
    assert dashboard.status_code == 200
    html = dashboard.get_data(as_text=True)
    assert "Yönetici Modülü" in html
    assert ">Ayarlar<" not in html
    assert "IMS Merkezi" in html


def test_region_manager_keeps_existing_scope_rules(client):
    login(client, "region.manager@example.com")
    # The synthetic fixture has no complete regional performance period, so the
    # permitted route may legitimately redirect to a data-state page. The
    # authorization contract is that own-region access is not rejected.
    allowed = client.get("/regions/101", follow_redirects=True)
    assert allowed.status_code == 200
    assert "Bu bölgenin yöneticisi değilsiniz." not in allowed.get_data(as_text=True)

    denied = client.get("/regions/201", follow_redirects=True)
    assert "Bu bölgenin yöneticisi değilsiniz." in denied.get_data(as_text=True)
    ims = client.get("/ims/", follow_redirects=True)
    assert "Bölge müdürü hesabınızla bu alanda değişiklik yapamazsınız." in ims.get_data(as_text=True)
