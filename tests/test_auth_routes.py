"""
Tests for Flask-Login / auth routing fix.

Verifies:
1. GET /login returns 200 with login page
2. POST /login authenticates successfully (redirects to dashboard)
3. Unauthenticated access to protected page redirects to /login?next=...
4. Successful login with next parameter returns user to intended page
5. Route map: /login exists and maps to auth.login
6. Open redirect is not possible via next parameter
"""
import os
import sys
import pytest
import tempfile
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
MIGRATIONS_DIR = str(Path(__file__).resolve().parents[1] / "migrations")


@pytest.fixture()
def app():
    os.environ.setdefault("APP_ENV", "development")
    os.environ.setdefault("SECRET_KEY", "test-secret-key")

    from app import create_app

    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "auth-test.db"

    class TestConfig:
        TESTING = True
        SECRET_KEY = "test-secret-key"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        LOGIN_DISABLED = False
        UPLOAD_FOLDER = __import__("pathlib").Path("/tmp/ipm_test/uploads")
        REPORT_FOLDER = __import__("pathlib").Path("/tmp/ipm_test/reports")
        BACKUP_FOLDER = __import__("pathlib").Path("/tmp/ipm_test/backups")
        LOG_FOLDER = __import__("pathlib").Path("/tmp/ipm_test/logs")
        TEMP_FOLDER = __import__("pathlib").Path("/tmp/ipm_test/temp")

    application = create_app(TestConfig)

    with application.app_context():
        from flask_migrate import upgrade
        from app.database import initialize_database
        from app.extensions import db
        upgrade(directory=MIGRATIONS_DIR)
        initialize_database()

        from app.models import User
        from werkzeug.security import generate_password_hash
        user = User(
            full_name="Test User",
            email="test@example.com",
            role="Representative",
            active=True,
        )
        user.password = generate_password_hash("password123")
        db.session.add(user)
        db.session.commit()

    yield application

    with application.app_context():
        from app.extensions import db
        db.session.remove()
    temp_dir.cleanup()


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Route map evidence
# ---------------------------------------------------------------------------

def test_login_route_exists_at_slash_login(app):
    """Route map: /login must exist and map to auth.login."""
    rules = {rule.endpoint: rule.rule for rule in app.url_map.iter_rules()}
    assert "auth.login" in rules, "auth.login endpoint not found in URL map"
    assert rules["auth.login"] == "/login", (
        f"auth.login is bound to '{rules['auth.login']}', expected '/login'"
    )


def test_login_manager_login_view(app):
    """login_manager.login_view must be auth.login and consistent with /login."""
    from app.extensions import login_manager
    assert login_manager.login_view == "auth.login"
    with app.test_request_context():
        from flask import url_for
        assert url_for("auth.login") == "/login"


# ---------------------------------------------------------------------------
# Scenario 1: GET /login returns login page (200)
# ---------------------------------------------------------------------------

def test_get_login_returns_200(client):
    response = client.get("/login")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Scenario 2: POST /login authenticates successfully
# ---------------------------------------------------------------------------

def test_post_login_success_redirects_to_dashboard(client):
    response = client.post(
        "/login",
        data={"email": "test@example.com", "password": "password123"},
        follow_redirects=False,
    )
    assert response.status_code in (301, 302)
    location = response.headers["Location"]
    # Should redirect to dashboard, not back to login
    assert "/login" not in location or "next" not in location


def test_post_login_wrong_password_stays_on_login(client):
    response = client.post(
        "/login",
        data={"email": "test@example.com", "password": "wrong"},
        follow_redirects=False,
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Scenario 3: Unauthenticated access to protected page redirects to /login?next=
# ---------------------------------------------------------------------------

def test_unauthenticated_access_redirects_to_login(client):
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code in (301, 302)
    location = response.headers["Location"]
    parsed = urlparse(location)
    assert parsed.path == "/login", (
        f"Expected redirect to /login, got '{parsed.path}'"
    )
    qs = parse_qs(parsed.query)
    assert "next" in qs, "Expected 'next' query parameter in redirect URL"


# ---------------------------------------------------------------------------
# Scenario 4: Successful login with next parameter returns user to intended page
# ---------------------------------------------------------------------------

def test_login_with_next_redirects_to_intended_page(client):
    response = client.post(
        "/login?next=/dashboard",
        data={"email": "test@example.com", "password": "password123"},
        follow_redirects=False,
    )
    assert response.status_code in (301, 302)
    location = response.headers["Location"]
    assert "/dashboard" in location


# ---------------------------------------------------------------------------
# Security: No open redirect via next parameter
# ---------------------------------------------------------------------------

def test_login_open_redirect_is_blocked(client):
    """next=//evil.com must not redirect off-site."""
    response = client.post(
        "/login?next=//evil.com/phish",
        data={"email": "test@example.com", "password": "password123"},
        follow_redirects=False,
    )
    assert response.status_code in (301, 302)
    location = response.headers["Location"]
    parsed = urlparse(location)
    assert parsed.netloc not in ("evil.com", "//evil.com"), (
        f"Open redirect detected: '{location}'"
    )


def test_login_absolute_url_redirect_is_blocked(client):
    """next=http://evil.com must not redirect off-site."""
    response = client.post(
        "/login?next=http://evil.com/phish",
        data={"email": "test@example.com", "password": "password123"},
        follow_redirects=False,
    )
    assert response.status_code in (301, 302)
    location = response.headers["Location"]
    parsed = urlparse(location)
    assert parsed.netloc != "evil.com", (
        f"Open redirect detected: '{location}'"
    )


# ---------------------------------------------------------------------------
# Dashboard: authenticated user gets 200 (not 500)
# ---------------------------------------------------------------------------

def test_dashboard_returns_200_for_authenticated_user(app):
    """Authenticated GET /dashboard/ must return 200 — not a 500 schema error."""
    client = app.test_client()
    # Log in first
    login_resp = client.post(
        "/login",
        data={"email": "test@example.com", "password": "password123"},
        follow_redirects=True,
    )
    assert login_resp.status_code == 200

    response = client.get("/dashboard/", follow_redirects=True)
    assert response.status_code == 200, (
        f"Expected 200 from /dashboard/, got {response.status_code}. "
        "Possible schema mismatch (missing IMSUpload columns)."
    )


def test_profile_page_and_user_menu_are_available_after_login(app):
    client = app.test_client()
    client.post("/login", data={"email": "test@example.com", "password": "password123"})

    profile = client.get("/profile")
    dashboard = client.get("/dashboard/", follow_redirects=True)

    assert profile.status_code == 200
    assert b"Profil Bilgileri" in profile.data
    assert b"/profile" in dashboard.data
    assert b"/logout" in dashboard.data


def test_global_representative_search_is_authenticated_and_returns_json(app):
    from app.extensions import db
    from app.models import Product, Representative

    with app.app_context():
        representative = Representative(rep_code="SEARCH-001", rep_name="Arama Temsilcisi", region="101", city="İstanbul", active=True)
        product = Product(product_code="SEARCH-PROD", product_name="Arama Ürünü", is_active=True)
        db.session.add_all([representative, product])
        db.session.commit()
    client = app.test_client()
    login = client.post("/login", data={"email": "test@example.com", "password": "password123"})
    assert login.status_code in (301, 302)
    response = client.get("/representatives/search?q=Arama")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["results"]
    assert payload["results"][0]["title"] == "Arama Temsilcisi"
    assert "/representatives/view/" in payload["results"][0]["url"]

    product_response = client.get("/representatives/search?q=Arama Ürünü")
    product_payload = product_response.get_json()
    assert any(item["kind"] == "product" and item["title"] == "Arama Ürünü" for item in product_payload["results"])


def test_mobile_navbar_contains_search_and_period_status(app):
    client = app.test_client()
    client.post("/login", data={"email": "test@example.com", "password": "password123"})

    response = client.get("/dashboard/", follow_redirects=True)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="globalRepresentativeSearch"' in html
    assert "Temsilci, brick veya ürün ara" in html
    assert 'class="navbar-mobile-status"' in html
    assert "Aktif" in html
    assert "Son IMS" in html


def test_representative_detail_renders_dynamic_market_analysis(app):
    from app.extensions import db
    from app.models import Representative

    with app.app_context():
        representative = Representative(rep_code="DETAIL-001", rep_name="Detay Temsilcisi", active=True)
        db.session.add(representative)
        db.session.commit()
        representative_id = representative.id

    client = app.test_client()
    client.post("/login", data={"email": "test@example.com", "password": "password123"})
    response = client.get(f"/representatives/view/{representative_id}?year=2026&month=8")

    assert response.status_code == 200
    assert "Detay Temsilcisi Ürün ve Brick Rekabet Analizi" in response.get_data(as_text=True)
    assert "Brick bazında kutu yoğunluğu ve dikkat alanları" in response.get_data(as_text=True)
    assert "Temsilci değiştir" in response.get_data(as_text=True)
