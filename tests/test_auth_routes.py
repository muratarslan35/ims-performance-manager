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


def test_region_search_opens_region_performance_screen(app):
    from app.extensions import db
    from app.models import Representative

    with app.app_context():
        db.session.add(Representative(rep_code="REGION-901", rep_name="Diyarbakır Temsilcisi", region="901", city="Diyarbakır", active=True))
        db.session.commit()

    client = app.test_client()
    client.post("/login", data={"email": "test@example.com", "password": "password123"})
    response = client.get("/representatives/search?q=Diyarbakır")
    region_item = next(item for item in response.get_json()["results"] if item["kind"] == "region")

    assert region_item["title"] == "901 Diyarbakır"
    assert "/regions/901" in region_item["url"]
    assert "3 aylık" in region_item["meta"]

    dotted_upper_response = client.get("/representatives/search?q=DİYARBAKIR")
    assert any(item["kind"] == "region" and item["title"] == "901 Diyarbakır" for item in dotted_upper_response.get_json()["results"])


def test_region_totals_include_inactive_vacant_positions(app):
    from app.extensions import db
    from app.models import Product, Representative, Target
    from app.services.region_performance_service import RegionPerformanceService

    with app.app_context():
        product = Product(product_code="VACANT-PROD", product_name="Boş Kadro Ürünü", is_active=True)
        employee = Representative(rep_code="REG-EMP", rep_name="Diyarbakır Çalışan", region="901", city="Diyarbakır", active=True)
        vacant_a = Representative(rep_code="REG-EMPTY-A", rep_name="Diyarbakır Boş", region="901", city="Diyarbakır", active=False)
        vacant_b = Representative(rep_code="REG-EMPTY-B", rep_name="Diyarbakır Kadro Boş", region="901", city="Diyarbakır", active=False)
        db.session.add_all([product, employee, vacant_a, vacant_b])
        db.session.commit()
        for representative, target in ((employee, 1000), (vacant_a, 2000), (vacant_b, 3000)):
            db.session.add(Target(year=2033, month=7, quarter="Q3", representative_id=representative.id, product_id=product.id, tl_target=target, unit_target=10))
        db.session.commit()

        report = RegionPerformanceService("901", 2033, 7).report()
        monthly = report["periods"]["monthly"]

        assert monthly["target_tl"] == 6000
        assert {row["representative_name"] for row in monthly["representatives"]} == {
            "Diyarbakır Çalışan", "Diyarbakır Boş", "Diyarbakır Kadro Boş"
        }
        assert report["active_count"] == 1
        assert report["vacant_count"] == 2


def test_region_performance_aggregates_real_monthly_three_six_and_yearly_data(app):
    from app.extensions import db
    from app.models import IMSSummary, IMSUpload, Product, Representative, Target
    from app.services.region_performance_service import RegionPerformanceService

    with app.app_context():
        product = Product(product_code="REG-PROD", product_name="Bölge Ürünü", is_active=True)
        rep_a = Representative(rep_code="REG-A", rep_name="Bölge Temsilcisi A", region="901", city="Diyarbakır", active=True)
        rep_b = Representative(rep_code="REG-B", rep_name="Bölge Temsilcisi B", region="901", city="Diyarbakır", active=True)
        db.session.add_all([product, rep_a, rep_b]); db.session.commit()
        for month in range(1, 7):
            quarter = f"Q{((month - 1) // 3) + 1}"
            upload = IMSUpload(file_name=f"region-{month}.xlsx", year=2032, month=month, quarter=quarter, status="COMPLETED")
            db.session.add(upload)
            db.session.flush()
            for rep, target, actual in [(rep_a, 1000, month * 100), (rep_b, 2000, month * 200)]:
                db.session.add(Target(year=2032, month=month, quarter=quarter, representative_id=rep.id, product_id=product.id, tl_target=target, unit_target=10))
                db.session.add(IMSSummary(upload_id=upload.id, year=2032, month=month, quarter=quarter, representative_id=rep.id, product_id=product.id, tl=actual, unit=1))
        db.session.commit()

        report = RegionPerformanceService("901", 2032, 6).report()

        assert report["representative_count"] == 2
        assert report["periods"]["monthly"]["target_tl"] == 3000
        assert report["periods"]["monthly"]["actual_tl"] == 1800
        assert report["periods"]["monthly"]["realization_percent"] == 60
        assert report["periods"]["quarterly"]["target_tl"] == 9000
        assert report["periods"]["quarterly"]["actual_tl"] == 4500
        assert report["periods"]["half_year"]["target_tl"] == 18000
        assert report["periods"]["half_year"]["actual_tl"] == 6300
        assert report["periods"]["yearly"]["actual_tl"] == 6300
        assert len(report["periods"]["yearly"]["months"]) == 6
        assert len(report["periods"]["yearly"]["representatives"]) == 2

    client = app.test_client()
    client.post("/login", data={"email": "test@example.com", "password": "password123"})
    page = client.get("/regions/901?year=2032&month=6")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "BÖLGESEL PERFORMANS MERKEZİ" in html
    assert "Ürün Bazlı 3 Aylık Realizasyon" in html
    assert "Bölge Temsilci Performansı" in html
    assert "Bölge Temsilcisi A" in html
    assert "BÖLGE ANALİZİ" in html
    yearly_panel = html.split('data-period-panel="yearly"', 1)[1]
    assert "Aylık Başarı Dağılımı" not in yearly_panel


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
    assert "IMS PERFORMANS TAKİP SİSTEMİ" in html


def test_login_and_register_show_corporate_system_name(app):
    client = app.test_client()
    assert "IMS PERFORMANS TAKİP SİSTEMİ" in client.get("/login").get_data(as_text=True)
    assert "IMS PERFORMANS TAKİP SİSTEMİ" in client.get("/register").get_data(as_text=True)
    css = Path("app/static/css/auth-branding.css").read_text(encoding="utf-8")
    assert "position: static" in css
    assert "background: transparent" in css
    assert "color: #111827" in css


def test_dashboard_keeps_national_kpis_single_and_regional_analysis_organized(app):
    client = app.test_client()
    client.post("/login", data={"email": "test@example.com", "password": "password123"})

    response = client.get("/dashboard/", follow_redirects=True)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert html.count("Aylık ₺ Hedefi") == 1
    assert html.count("Gerçekleşen Çıkış") == 1
    assert html.count("TL Realizasyonu") == 1
    assert "executive-market-kpis" not in html
    assert "Bölge Pazar Payları Sıralaması" in html
    assert "Bölgesel Ürün Bazlı Rekabet Analizi" in html
    assert 'id="regionalCompetitionTable"' in html
    assert 'data-competition-filter="risk"' in html
    assert "Pay = Şirket IMS ÷ Toplam Pazar" in html
    assert "Pazar Büyüklüğü" not in html
    assert "Bölgesel Aksiyon" not in html
    assert "Hedef Kutu" in html
    assert "Gerçekleşen Kutu" in html
    assert "Kutu Realizasyonu" in html
    assert "Türkiye Bölge Haritası" in html
    assert "Excel Bölge Yerleşimi" not in html
    assert "Türkiye temsili satış bölgesi haritası" in html
    assert "Ürün Performans Tablosu" in html
    assert "Türkiye Performans Özeti" not in html
    assert 'id="mapSelectedInfo"' in html
    assert "901 · DİYARBAKIR" in html
    assert "Batman" in html and "Şanlıurfa" in html and "Mardin" in html
    assert "DOĞU VE GÜNEYDOĞU BÖLGESİ" not in html
    assert "Van" in html
    assert "Bölge analizini aç" in Path("app/static/js/dashboard.js").read_text(encoding="utf-8")
    assert "province-layer" not in html
    assert 'id="productValueLegend"' in Path("app/templates/dashboard.html").read_text(encoding="utf-8")
    assert "product-performance-layout" in Path("app/templates/dashboard.html").read_text(encoding="utf-8")
    dashboard_template = Path("app/templates/dashboard.html").read_text(encoding="utf-8")
    assert dashboard_template.index("Ürün Performans Tablosu") < dashboard_template.index('id="productDonutChart"')
    assert "Toplam Ciro Dağılımı" in dashboard_template
    assert "escapeDashboardHtml" in Path("app/static/js/dashboard.js").read_text(encoding="utf-8")
    assert 'id="executiveKpiLayout"' in html
    assert 'id="productPerformanceSection"' in html
    assert 'id="turkeyMapSection"' in html
    assert 'id="imsTurkeyRankingSection"' in html
    assert 'id="regionalMarketShareRankingSection"' in html
    assert "IMS Türkiye Sıralaması" in html
    assert "Bölge Pazar Payları Sıralaması" in html
    dashboard_js = Path("app/static/js/dashboard.js").read_text(encoding="utf-8")
    assert dashboard_js.index('"productPerformanceSection"') < dashboard_js.index('"turkeyMapSection"') < dashboard_js.index('"imsTurkeyRankingSection"') < dashboard_js.index('"regionalMarketShareRankingSection"')
    assert 'id="aiExecutiveSummary"' in html
    assert "Gerçekleşen Ciro" in html
    assert "Hedef Açığı" in html
    assert "Aksiyon Bölgesi" in html
    assert "Aksiyon Ürünü" in html
    assert "Risk Puanı" not in html
    assert "Beklenen Prim" not in html
    assert "Kaçırılan Prim" not in html
    assert 'appendChild(executiveSummary)' in dashboard_js
    assert "region-realization-value" in Path("app/templates/dashboard.html").read_text(encoding="utf-8")
    assert "window.location.assign(detailUrl)" in Path("app/static/js/dashboard.js").read_text(encoding="utf-8")


def test_user_visible_recovery_labels_are_turkish():
    visible_files = [
        Path("app/templates/simulation.html"), Path("app/templates/ims.html"),
        Path("app/templates/settings.html"), Path("app/templates/partials/sidebar.html"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in visible_files)
    assert "Recovery" not in combined
    assert "Telafi" in combined


def test_national_dashboard_box_metrics_use_target_and_weekly_sources(app):
    from datetime import datetime

    from app.extensions import db
    from app.models import IMSRawData, IMSUpload, Product, Representative, Target
    from app.query.dashboard_query import DashboardQuery
    from app.query.filters import DashboardFilterParams

    with app.app_context():
        product = Product(product_code="BOX-KPI", product_name="Kutu KPI Ürünü", is_active=True)
        representative = Representative(rep_code="BOX-REP", rep_name="Kutu Temsilcisi", active=True)
        db.session.add_all([product, representative])
        db.session.commit()
        upload = IMSUpload(file_name="box-kpi.xlsx", year=2031, month=5, status="COMPLETED", completed_at=datetime.utcnow())
        db.session.add(upload)
        db.session.commit()
        db.session.add_all([
            Target(year=2031, month=5, quarter="Q2", representative_id=representative.id, product_id=product.id, unit_target=200, tl_target=20000),
            IMSRawData(upload_id=upload.id, year=2031, month=5, quarter="Q2", source_row=2, sheet_name="BAKİYE", sheet_type="dashboard_balance_national", product_id=product.id, unit=20000, tl=12000, raw_json="{}"),
            IMSRawData(upload_id=upload.id, year=2031, month=5, quarter="Q2", source_row=2, sheet_name="TTS", sheet_type="dashboard_weekly_units", product_id=product.id, unit=150, tl=0, raw_json="{}"),
        ])
        db.session.commit()

        result = DashboardQuery().load_national_dashboard_metrics(DashboardFilterParams(year=2031, month=5))

        assert result["unit_target"] == 200
        assert result["unit_actual"] == 150
        assert result["unit_realization_percent"] == 75
        assert result["products"][0]["unit_realization_percent"] == 75


def test_simulation_page_supports_repeat_calculation_and_dual_gap_metrics(app):
    client = app.test_client()
    client.post("/login", data={"email": "test@example.com", "password": "password123"})

    response = client.get("/simulation/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="simulationSubmit"' in html
    assert "Yeni Hesaplama Yap" in html
    assert "finally" in html
    assert "setButtonState(false,completed)" in html
    assert "Kutu Eksiği" in html
    assert "₺ Eksiği" in html
    assert "item.remaining_box" in html
    assert "item.remaining_tl" in html
    assert "risk-row-high" in html
    assert "Temsilci Prim Hedef Özeti" in html
    assert 'id="targetSnapshot"' in html
    assert "Temsilci Saha Aksiyon Planı" in html
    assert 'id="actionPlanTable"' in html
    assert "item.daily_box" in html
    assert "item.daily_tl" in html


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


def test_product_management_uses_simplified_safe_fields(app):
    from app.models import Product

    client = app.test_client()
    client.post("/login", data={"email": "test@example.com", "password": "password123"})

    page = client.get("/products/")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "Prime Esas" in html
    assert 'name="ims_name"' not in html
    assert 'name="category"' not in html
    assert 'name="required_percent"' not in html
    assert "<th>IMS Adı</th>" not in html
    assert "<th>Kategori</th>" not in html
    assert "<th>Hedef</th>" not in html

    response = client.post("/products/add", data={
        "product_code": "YENI-URUN",
        "product_name": "Yeni Ürün",
        "molecule": "Örnek etken madde",
        "strength": "10 mg",
        "dosage_form": "Tablet",
        "unit_price": "25.50",
        "display_order": "20",
        "prime": "on",
        "include_total_tl": "on",
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        product = Product.query.filter_by(product_code="YENI-URUN").one()
        assert product.product_name == "Yeni Ürün"
        assert product.ims_name == "Yeni Ürün"
        assert product.category is None
        assert product.required_percent == 0
        assert product.molecule == "Örnek etken madde"


def test_verified_product_active_ingredients_are_migrated():
    migration = Path("migrations/versions/j5e6f7a8b9c0_update_product_active_ingredients.py").read_text(encoding="utf-8")
    expected = {
        "ACNEMIX": "Benzoil peroksit + Eritromisin",
        "BRIMODER": "Brimonidin tartarat",
        "FENTIVAG": "Fentikonazol nitrat",
        "MIXOVUL": "Metronidazol + Mikonazol nitrat + Lidokain",
        "MONUROL": "Fosfomisin trometamol",
        "STIDERM": "Mepiramin maleat + Lidokain hidroklorür + Dekspantenol",
        "TRAVAZOL": "İzokonazol nitrat + Diflukortolon valerat",
    }
    for code, ingredient in expected.items():
        assert code in migration
        assert ingredient in migration
