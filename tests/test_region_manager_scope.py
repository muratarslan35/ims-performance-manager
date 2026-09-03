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
        from app.models import Representative, RepresentativeBrickAssignment, User
        from app.region_manager import RegionManagerScope

        upgrade(directory=MIGRATIONS_DIR)
        initialize_database()

        rep_101 = Representative(rep_code="RM101", rep_name="101 Temsilci", region="101 ADANA", city="ADANA", email="rep101@example.com", active=True)
        teammate_101 = Representative(rep_code="RM102", rep_name="101 Ekip Arkadaşı", region="101 ADANA", city="ADANA", active=True)
        rep_201 = Representative(rep_code="RM201", rep_name="201 Temsilci", region="201 ANKARA", city="ANKARA", active=True)
        manager = User(
            full_name="101 Bölge Müdürü",
            email="manager101@example.com",
            password=generate_password_hash("password123"),
            role="Manager",
            active=True,
        )
        field_user = User(
            full_name="101 Temsilci", email="rep101@example.com",
            password=generate_password_hash("password123"), role="Representative", active=True,
        )
        db.session.add_all([rep_101, teammate_101, rep_201, manager, field_user])
        db.session.flush()
        db.session.add(RegionManagerScope(user_id=manager.id, region_code="101", manager_type="region"))
        db.session.add_all([
            RepresentativeBrickAssignment(representative_id=rep_101.id, year=2026, month=1, brick="101 BRICK", active=True),
            RepresentativeBrickAssignment(representative_id=rep_201.id, year=2026, month=1, brick="201 BRICK", active=True),
        ])
        db.session.commit()
        application.config["TEST_REP_101"] = rep_101.id
        application.config["TEST_REP_201"] = rep_201.id
        application.config["TEST_TEAMMATE_101"] = teammate_101.id

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


def test_production_acceptance_session_respects_strong_protection(app, client):
    from app.models import User
    from verify_region_manager_production import _login_as

    with app.app_context():
        manager = User.query.filter_by(email="manager101@example.com").one()
        manager_id = manager.id
    _login_as(client, manager_id)
    response = client.get("/dashboard/")
    assert response.status_code == 200


def test_field_portal_check_is_fail_closed_outside_request_context(app):
    from app.region_manager import is_field_portal

    with app.app_context():
        assert is_field_portal() is False


def login_admin(client):
    return client.post(
        "/login",
        data={"email": "admin@ipm.local", "password": "Admin12345", "portal": "manager"},
        follow_redirects=False,
    )


def login_representative(client):
    return client.post(
        "/login",
        data={"email": "rep101@example.com", "password": "password123", "portal": "representative"},
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
            "manager_type": "region",
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
        assert scope.manager_type == "region"


def test_regional_manager_sees_only_own_representatives(app, client):
    login_manager(client)
    response = client.get("/representatives/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "101 Temsilci" in html
    assert "201 Temsilci" not in html


def test_regional_manager_can_reset_only_own_representative_password(app, client):
    login_manager(client)

    own_id = app.config["TEST_REP_101"]
    response = client.post(f"/representatives/reset-password/{own_id}", follow_redirects=True)
    assert response.status_code == 200
    assert "şifresi geçici şifre olarak sıfırlandı" in response.get_data(as_text=True)

    with app.app_context():
        from app.models import User
        user = User.query.filter_by(email="rep101@example.com").one()
        assert check_password_hash(user.password, "Bilim12345")

    client.get("/logout")
    login = client.post(
        "/login",
        data={"email": "rep101@example.com", "password": "Bilim12345", "portal": "representative"},
    )
    assert login.status_code == 302
    changed = client.post(
        "/profile",
        data={
            "action": "password",
            "current_password": "Bilim12345",
            "password": "YeniBilim12345",
            "password_confirm": "YeniBilim12345",
        },
        follow_redirects=True,
    )
    assert "Şifreniz güncellendi" in changed.get_data(as_text=True)

    client.get("/logout")
    login_manager(client)
    other_id = app.config["TEST_REP_201"]
    response = client.post(f"/representatives/reset-password/{other_id}", follow_redirects=True)
    assert response.status_code == 200
    assert "şifresini sıfırlama yetkiniz yok" in response.get_data(as_text=True)


def test_representative_cannot_reset_password_from_management_endpoint(app, client):
    login_representative(client)
    own_id = app.config["TEST_REP_101"]
    response = client.post(f"/representatives/reset-password/{own_id}", follow_redirects=True)
    assert response.status_code == 200
    assert "Temsilci hesabınızla bu alana erişemezsiniz" in response.get_data(as_text=True)


def test_representative_portal_hides_and_blocks_representative_management(app, client):
    login_representative(client)

    dashboard = client.get("/dashboard/")
    html = dashboard.get_data(as_text=True)
    assert "Temsilciler</span>" not in html
    assert "Uyarılar ve Aksiyonlar" not in html
    assert "Hızlı İşlemler" not in html
    assert "Hedef Yönetimi" not in html

    response = client.get("/representatives/", follow_redirects=True)
    assert response.status_code == 200
    assert "Temsilci hesabınızla bu alana erişemezsiniz" in response.get_data(as_text=True)


def test_dashboard_heading_reflects_selected_portal(client):
    login_manager(client)
    manager_html = client.get("/dashboard/").get_data(as_text=True)
    assert "101 Bölge Müdürü" in manager_html
    assert "Yönetici Görünümü" in manager_html
    assert "Türkiye geneli yönetici görünümü" not in manager_html

    client.get("/logout")
    login_representative(client)
    representative_html = client.get("/dashboard/").get_data(as_text=True)
    assert "101 Temsilci" in representative_html
    assert "Temsilci Görünümü" in representative_html
    assert "Türkiye geneli yönetici görünümü" not in representative_html


def test_regional_manager_cannot_open_other_region_detail(client):
    login_manager(client)
    response = client.get("/regions/201", follow_redirects=True)
    assert response.status_code == 200
    assert "Bu bölgenin yöneticisi değilsiniz." in response.get_data(as_text=True)


def test_regional_manager_cannot_open_other_representative(app, client):
    login_manager(client)
    response = client.get(f"/representatives/view/{app.config['TEST_REP_201']}", follow_redirects=True)
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

    denied_q = client.get(f"/quarter?representative_id={app.config['TEST_REP_201']}", follow_redirects=True)
    assert "Bu bölgenin yöneticisi değilsiniz." in denied_q.get_data(as_text=True)


def test_global_search_filters_cross_region_results(client):
    login_manager(client)
    response = client.get("/representatives/search?q=Temsilci")
    assert response.status_code == 200
    payload = response.get_json()
    titles = [item["title"] for item in payload["results"]]
    assert "101 Temsilci" in titles
    assert "201 Temsilci" not in titles


def test_regional_manager_can_view_manager_module_but_cannot_mutate(client):
    login_manager(client)
    response = client.get("/manager-users/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Yönetici Modülü" in html
    assert "Yeni Yönetici" not in html

    denied = client.post(
        "/manager-users/create",
        data={
            "full_name": "Yetkisiz",
            "email": "forbidden@example.com",
            "password": "password123",
            "manager_type": "marketing",
        },
        follow_redirects=True,
    )
    assert "yönetici ekleme veya düzenleme yetkisine sahip değildir" in denied.get_data(as_text=True)


def test_representative_portal_is_region_scoped_and_management_is_fail_closed(app, client):
    login_representative(client)
    dashboard = client.get("/dashboard/")
    assert dashboard.status_code == 200
    html = dashboard.get_data(as_text=True)
    assert 'data-codes="101" data-allowed="true"' in html
    assert 'data-codes="201" data-allowed="false"' in html
    assert "Bölge Güncelle" not in html

    own_team = client.get(f"/representatives/view/{app.config['TEST_TEAMMATE_101']}", follow_redirects=True)
    assert "Sadece kendi bölgenizdeki temsilcilere erişebilirsiniz." not in own_team.get_data(as_text=True)
    cross_region = client.get(f"/representatives/view/{app.config['TEST_REP_201']}", follow_redirects=True)
    assert "Bu bölgenin yöneticisi değilsiniz." in cross_region.get_data(as_text=True)

    search = client.get("/representatives/search?q=Temsilci").get_json()
    titles = [item["title"] for item in search["results"]]
    assert "101 Temsilci" in titles
    assert "201 Temsilci" not in titles

    for path in ("/market-analysis", "/targets/", "/products/", "/representatives/territory-management"):
        denied = client.get(path, follow_redirects=False)
        assert denied.status_code in (301, 302)
        assert denied.headers["Location"].endswith("/dashboard/")


def test_representative_cross_region_setting_unlocks_map_and_routes_on_every_viewport(app, client):
    from app.extensions import db
    from app.models import Setting

    with app.app_context():
        db.session.add(Setting(
            setting_key="ACCESS.representative.cross_region_details",
            setting_value="true",
            category="Erişim Yetkisi",
            description="Farklı bölge detayları",
        ))
        db.session.commit()

    login_representative(client)
    dashboard = client.get("/dashboard/")
    assert dashboard.status_code == 200
    html = dashboard.get_data(as_text=True)
    assert 'data-codes="101" data-allowed="true"' in html
    assert 'data-codes="201" data-allowed="true"' in html
    assert "field_portal_region_restricted" not in html

    cross_region = client.get("/regions/201", follow_redirects=True)
    assert cross_region.status_code == 200
    assert "Bu bölgenin yöneticisi değilsiniz." not in cross_region.get_data(as_text=True)

    search = client.get("/representatives/search?q=Temsilci").get_json()
    assert "201 Temsilci" in [item["title"] for item in search["results"]]


def test_regional_manager_assignment_scope_blocks_cross_region_mutation(app, client):
    login_manager(client)
    page = client.get("/representatives/territory-management?year=2026&month=1")
    html = page.get_data(as_text=True)
    assert "101 BRICK" in html
    assert "201 BRICK" not in html

    with app.app_context():
        from app.models import RepresentativeBrickAssignment
        foreign = RepresentativeBrickAssignment.query.filter_by(brick="201 BRICK").one()
        foreign_id = foreign.id
    denied = client.post(
        f"/representatives/territory-management/{foreign_id}/status",
        data={"active": "0"}, follow_redirects=True,
    )
    assert "Bu bölgenin yöneticisi değilsiniz." in denied.get_data(as_text=True)

    with app.app_context():
        from app.models import RepresentativeBrickAssignment
        own = RepresentativeBrickAssignment.query.filter_by(brick="101 BRICK").one()
        own_id = own.id
    denied_transfer = client.post(
        f"/representatives/territory-management/{own_id}/transfer",
        data={"target_representative_id": app.config["TEST_REP_201"]}, follow_redirects=True,
    )
    assert "Bu bölgenin yöneticisi değilsiniz." in denied_transfer.get_data(as_text=True)


def test_admin_toggle_allows_cross_region_assignment_mutation(app, client):
    with app.app_context():
        from app.extensions import db
        from app.models import RepresentativeBrickAssignment, Setting
        db.session.add(Setting(
            setting_key="ACCESS.region.cross_region_assignments",
            setting_value="1",
            category="Erişim Yetkisi",
            description="Farklı bölge brick ataması",
        ))
        db.session.commit()
        foreign_id = RepresentativeBrickAssignment.query.filter_by(brick="201 BRICK").one().id

    login_manager(client)
    page = client.get("/representatives/territory-management?year=2026&month=1")
    assert "201 BRICK" in page.get_data(as_text=True)

    changed = client.post(
        f"/representatives/territory-management/{foreign_id}/status",
        data={"active": "0"},
        follow_redirects=True,
    )
    assert "201 BRICK çalışma alanı pasife alındı" in changed.get_data(as_text=True)
    with app.app_context():
        from app.models import RepresentativeBrickAssignment
        assert RepresentativeBrickAssignment.query.get(foreign_id).active is False


def test_murat_asan_manager_keeps_unrestricted_special_access(app):
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
        assert is_privileged_manager(murat)
        assert not is_regional_manager(murat)
