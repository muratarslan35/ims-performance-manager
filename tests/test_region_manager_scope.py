import os
import tempfile
from pathlib import Path

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

MIGRATIONS_DIR = str(Path(__file__).resolve().parents[1] / "migrations")


@pytest.fixture()
def app():
    os.environ.setdefault("APP_ENV", "development")
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "region-manager.db"

    class TestConfig:
        TESTING = True
        SECRET_KEY = "region-manager-test"
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

        rep_101 = Representative(
            rep_code="RM101",
            rep_name="101 Temsilci",
            region="101 ADANA",
            city="ADANA",
            active=True,
        )
        rep_201 = Representative(
            rep_code="RM201",
            rep_name="201 Temsilci",
            region="201 ANKARA",
            city="ANKARA",
            active=True,
        )
        manager = User(
            full_name="101 Bölge Müdürü",
            email="manager101@example.com",
            password=generate_password_hash("password123"),
            role="Manager",
            active=True,
        )
        db.session.add_all([rep_101, rep_201, manager])
        db.session.flush()
        db.session.add(RegionManagerScope(user_id=manager.id, region_code="101"))
        db.session.commit()
        application.config["TEST_REP_101"] = rep_101.id
        application.config["TEST_REP_201"] = rep_201.id

    yield application

    with application.app_context():
        from app.extensions import db
        db.session.remove()
    temp_dir.cleanup()


@pytest.fixture()
def client(app):
    return app.test_client()


def login_manager(client):
    return client.post(
        "/login",
        data={"email": "manager101@example.com", "password": "password123", "portal": "manager"},
        follow_redirects=False,
    )


def login_admin(client):
    return client.post(
        "/login",
        data={"email": "admin@ipm.local", "password": "Admin12345", "portal": "manager"},
        follow_redirects=False,
    )


def test_manager_module_creates_login_user_with_region_scope(app, client):
    login_admin(client)
    response = client.post(
        "/manager-users/create",
        data={
            "full_name": "Yeni Bölge Müdürü",
            "email": "new.manager@example.com",
            "password": "StrongPass123",
            "region_code": "201",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        from app.models import User
        from app.region_manager import RegionManagerScope

        user = User.query.filter_by(email="new.manager@example.com").one()
        scope = RegionManagerScope.query.filter_by(user_id=user.id).one()
        assert user.role == "Manager"
        assert user.active is True
        assert check_password_hash(user.password, "StrongPass123")
        assert scope.region_code == "201"


def test_regional_manager_sees_only_own_representatives(app, client):
    login_manager(client)
    response = client.get("/representatives/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "101 Temsilci" in html
    assert "201 Temsilci" not in html


def test_regional_manager_cannot_open_other_region_detail(client):
    login_manager(client)
    response = client.get("/regions/201", follow_redirects=True)
    assert response.status_code == 200
    assert "Bu bölgenin yöneticisi değilsiniz." in response.get_data(as_text=True)


def test_regional_manager_cannot_open_other_representative(app, client):
    login_manager(client)
    response = client.get(
        f"/representatives/view/{app.config['TEST_REP_201']}",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Bu bölgenin yöneticisi değilsiniz." in response.get_data(as_text=True)


def test_regional_manager_cannot_use_ims_settings_or_master_mutations(client):
    login_manager(client)
    for path in ("/ims/", "/settings/", "/targets/", "/matching/", "/products/"):
        response = client.get(path, follow_redirects=True)
        assert response.status_code == 200
        assert "Bölge müdürü hesabınızla bu alanda değişiklik yapamazsınız." in response.get_data(as_text=True)


def test_simulation_and_q_are_region_scoped(app, client):
    login_manager(client)

    simulation = client.get("/simulation/")
    assert simulation.status_code == 200
    simulation_html = simulation.get_data(as_text=True)
    assert "101 Temsilci" in simulation_html
    assert "201 Temsilci" not in simulation_html

    denied = client.get(f"/simulation/representative/{app.config['TEST_REP_201']}")
    assert denied.status_code == 403
    assert denied.get_json()["message"] == "Bu bölgenin yöneticisi değilsiniz."

    quarter = client.get("/quarter")
    assert quarter.status_code == 200
    quarter_html = quarter.get_data(as_text=True)
    assert "101 Temsilci" in quarter_html
    assert "201 Temsilci" not in quarter_html

    denied_q = client.get(
        f"/quarter?representative_id={app.config['TEST_REP_201']}",
        follow_redirects=True,
    )
    assert "Bu bölgenin yöneticisi değilsiniz." in denied_q.get_data(as_text=True)


def test_global_search_filters_cross_region_results(client):
    login_manager(client)
    response = client.get("/representatives/search?q=Temsilci")
    assert response.status_code == 200
    payload = response.get_json()
    titles = [item["title"] for item in payload["results"]]
    assert "101 Temsilci" in titles
    assert "201 Temsilci" not in titles


def test_regional_manager_cannot_open_manager_user_module(client):
    login_manager(client)
    response = client.get("/manager-users/", follow_redirects=True)
    assert response.status_code == 200
    assert "Bölge müdürü hesabınızla bu alanda değişiklik yapamazsınız." in response.get_data(as_text=True)


def test_murat_asan_manager_keeps_unrestricted_special_access(app):
    from app.access_control import has_dual_portal_access
    from app.extensions import db
    from app.models import User
    from app.region_manager import is_privileged_manager, is_regional_manager

    with app.app_context():
        murat = User(
            full_name="Murat Asan",
            email="murat.asan@bilimilac.com",
            password=generate_password_hash("password123"),
            role="Manager",
            active=True,
        )
        db.session.add(murat)
        db.session.commit()
        assert has_dual_portal_access(murat)
        assert is_privileged_manager(murat)
        assert not is_regional_manager(murat)
