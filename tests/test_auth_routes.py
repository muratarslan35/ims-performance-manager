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


def test_region_totals_prefer_official_workbook_subtotal_but_keep_person_allocations(app):
    from app.extensions import db
    from app.models import IMSRawData, IMSUpload, IMSSummary, Product, Representative, Target
    from app.query.dashboard_query import DashboardQuery
    from app.query.filters import DashboardFilterParams
    from app.services.region_performance_service import RegionPerformanceService
    import json

    with app.app_context():
        product = Product(product_code="OFFICIAL-REG", product_name="Resmi Bölge Ürünü", is_active=True)
        rep_a = Representative(rep_code="OFF-A", rep_name="Resmi A", region="901", city="Diyarbakır", active=True)
        rep_b = Representative(rep_code="OFF-B", rep_name="Resmi B", region="901", city="Diyarbakır", active=False)
        db.session.add_all([product, rep_a, rep_b]); db.session.flush()
        upload = IMSUpload(file_name="official-region.xlsx", year=2035, month=1, quarter="Q1", status="COMPLETED")
        db.session.add(upload); db.session.flush()
        for rep, target, actual in ((rep_a, 4000, 400), (rep_b, 3000, 300)):
            db.session.add(Target(year=2035, month=1, quarter="Q1", representative_id=rep.id, product_id=product.id, tl_target=target, unit_target=10))
            db.session.add(IMSSummary(upload_id=upload.id, year=2035, month=1, quarter="Q1", representative_id=rep.id, product_id=product.id, tl=actual, unit=2))
        db.session.add_all([
            IMSRawData(upload_id=upload.id, year=2035, month=1, quarter="Q1", sheet_name="BAKİYE", sheet_type="dashboard_balance_region", source_row=0, product_id=product.id, representative="901 DIYARBAKIR", territory="901 DIYARBAKIR", unit=6000, tl=650, raw_json=json.dumps({"target_tl":6000})),
            IMSRawData(upload_id=upload.id, year=2035, month=1, quarter="Q1", sheet_name="TTS HAFTALIK ÇIKIŞLARI", sheet_type="dashboard_weekly_region", source_row=0, product_id=product.id, representative="901 DIYARBAKIR", territory="901 DIYARBAKIR", unit=9, tl=650, raw_json=json.dumps({"actual_tl":650,"actual_unit":9})),
        ])
        db.session.commit()

        report = RegionPerformanceService("901", 2035, 1).report()
        monthly = report["periods"]["monthly"]
        assert monthly["target_tl"] == 6000
        assert monthly["actual_tl"] == 650
        assert sum(row["target_tl"] for row in monthly["representatives"]) == 7000
        assert monthly["months"][0]["source"] == "OFFICIAL_REGION_SUBTOTAL"

        rows = DashboardQuery().load_region_performance(DashboardFilterParams(year=2035, month=1))
        row = next(item for item in rows if str(item.region) == "901")
        assert row.tl_target == 6000
        assert row.tl_actual == 650
        assert row.unit_actual == 9
        assert row.unit_target == 20


def test_target_analysis_groups_products_under_one_representative(app):
    from app.extensions import db
    from app.models import Product, Representative, Target

    with app.app_context():
        representative = Representative(
            rep_code="TARGET-GROUP", rep_name="Hedef Temsilcisi",
            region="901", city="Diyarbakır", active=True,
        )
        products = [
            Product(product_code="TARGET-A", product_name="Hedef Ürün A", is_active=True),
            Product(product_code="TARGET-B", product_name="Hedef Ürün B", is_active=True),
        ]
        db.session.add_all([representative, *products])
        db.session.flush()
        db.session.add_all([
            Target(year=2034, month=1, quarter="Q1", representative_id=representative.id,
                   product_id=product.id, tl_target=1000, unit_target=10)
            for product in products
        ])
        db.session.commit()

    client = app.test_client()
    client.post("/login", data={"email": "test@example.com", "password": "password123"})
    response = client.get("/targets/analysis?year=2034&month=1")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert html.count("Hedef Temsilcisi") == 1
    assert 'data-bs-target="#targetAnalysisRep' in html
    assert "Hedef Ürün A" in html
    assert "Hedef Ürün B" in html


def test_box_target_calculation_preserves_authoritative_unit_target():
    from app.services.target_box_calculation_service import TargetBoxCalculationService

    assert TargetBoxCalculationService.unit_target(1005902, 111.655) == 1005902


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
        assert len(report["annual_realization"]) == 12
        assert [row["percent"] for row in report["annual_realization"][:6]] == [10, 20, 30, 40, 50, 60]
        assert all(row["percent"] is None for row in report["annual_realization"][6:])

    client = app.test_client()
    client.post("/login", data={"email": "test@example.com", "password": "password123"})
    page = client.get("/regions/901?year=2032&month=6")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "BÖLGESEL PERFORMANS MERKEZİ" in html
    assert "Ürün Bazlı 3 Aylık Realizasyon" in html
    assert "Bölge Temsilci Performansı" in html
    assert "12 Aylık Bölge Realizasyonu" in html
    assert "annual-realization-chart.js" in html
    assert "Bölge Temsilcisi A" in html
    assert "BÖLGE ANALİZİ" in html
    yearly_panel = html.split('data-period-panel="yearly"', 1)[1]
    assert "Aylık Başarı Dağılımı" not in yearly_panel


def test_dashboard_competition_uses_latest_upload_with_real_excel_tl_rows(app):
    from app.extensions import db
    from app.models import CompetitionData, IMSUpload
    from app.query.dashboard_query import DashboardQuery
    from app.query.filters import DashboardFilterParams

    with app.app_context():
        source_upload = IMSUpload(file_name="ocak-rekabet.xlsx", year=2035, month=1, status="COMPLETED")
        db.session.add(source_upload)
        db.session.flush()
        db.session.add_all([
            CompetitionData(
                upload_id=source_upload.id, sheet_name="AYLIK REKABET TL", period_type="MONTHLY",
                year=2035, month=1, territory="201 KADIKOY", subterritory="KADIKOY MERKEZ",
                product_group="TRAVAZOL GRUP", product_name="TRAVAZOL KREM", metric_type="TL",
                metric_value=125000, source_row=5,
            ),
            CompetitionData(
                upload_id=source_upload.id, sheet_name="AYLIK REKABET TL", period_type="MONTHLY",
                year=2035, month=1, territory="201 KADIKOY", subterritory="KADIKOY MERKEZ",
                product_group="TRAVAZOL GRUP", product_name="TRAVOCORT KREM", metric_type="TL",
                metric_value=75000, source_row=5,
            ),
        ])
        db.session.flush()
        empty_newer_upload = IMSUpload(file_name="bos-yukleme.xlsx", year=2035, month=1, status="COMPLETED")
        db.session.add(empty_newer_upload)
        db.session.commit()

        filters = DashboardFilterParams(year=2035, month=1)
        query = DashboardQuery()
        overview = query.load_competition_overview(filters)
        regional = query.load_regional_competition_rows(filters)

        assert len(overview) == 1
        assert overview[0].product_group == "TRAVAZOL GRUP"
        assert overview[0].market_tl == 200000
        assert len(regional) == 2
        assert {row.product_name for row in regional} == {"TRAVAZOL KREM", "TRAVOCORT KREM"}


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
    assert "1. Ürün Bazlı Analiz" in response.get_data(as_text=True)
    assert "2. Brick Bazlı Analiz" in response.get_data(as_text=True)
    assert "Brick bazlı ürün karşılaştırması" in response.get_data(as_text=True)
    assert "Temsilci satışı" in response.get_data(as_text=True)
    assert "Rakip kutu toplamı" in response.get_data(as_text=True)
    assert "Toplam kutu pazarı" in response.get_data(as_text=True)
    assert "Pazardan alınan pay" in response.get_data(as_text=True)
    assert "Ürün realizasyonu" not in response.get_data(as_text=True)
    assert 'data-brick-target=' in response.get_data(as_text=True) or "Brick verisi bulunmuyor" in response.get_data(as_text=True)
    assert "Temsilci değiştir" in response.get_data(as_text=True)
    assert "Aylık ürün değişimi ve rakip baskısı" in response.get_data(as_text=True)
    assert "12 Aylık Toplam Realizasyon" in response.get_data(as_text=True)
    assert "annual-realization-chart.js" in response.get_data(as_text=True)


def test_regional_vacancies_are_visible_without_technical_prefix_and_general_is_hidden(app):
    from app.extensions import db
    from app.models import Representative, RepresentativeBrickAssignment
    from app.representatives import _representative_display_name
    from app.services.period_service import PeriodService

    assert _representative_display_name("ATANMAMIŞ · 901 DIYARBAKIR · DIYARBAKIR BOS") == "901 DIYARBAKIR BOS"
    assert _representative_display_name("ATANMAMIS-901 DIYARBAKIR BOS") == "901 DIYARBAKIR BOS"

    with app.app_context():
        active_period = PeriodService.get_active_period()
        vacancy = Representative(
            rep_code="UNASSIGNED201-KADIKOY-BOS",
            rep_name="ATANMAMIŞ · 201 KADIKÖY · KADIKÖY BOŞ",
            region="201 KADIKÖY",
            city="KADIKÖY",
            active=True,
        )
        db.session.add(vacancy)
        db.session.add(Representative(
            rep_code="UNASSIGNEDGENERAL",
            rep_name="ATANMAMIŞ · GENEL",
            active=True,
        ))
        db.session.flush()
        db.session.add(RepresentativeBrickAssignment(
            representative_id=vacancy.id,
            year=active_period["year"],
            month=active_period["month"],
            quarter=f"Q{((active_period['month'] - 1) // 3) + 1}",
            brick="KADIKÖY MERKEZ",
            source="AUTO",
            active=True,
        ))
        db.session.commit()
        vacancy_id = vacancy.id

    client = app.test_client()
    client.post("/login", data={"email": "test@example.com", "password": "password123"})

    representative_page = client.get("/representatives/").get_data(as_text=True)
    representative_search = client.get("/representatives/search?q=KADIKOY BOS").get_json()
    brick_search = client.get("/representatives/search?q=KADIKÖY MERKEZ").get_json()

    assert "201 KADIKÖY BOŞ" in representative_page
    assert "ATANMAMIŞ · GENEL" not in representative_page
    assert any(item["kind"] == "representative" and "ATANMAMIŞ" not in item["title"] for item in representative_search["results"])
    assert any(item["kind"] == "brick" and "ATANMAMIŞ" not in item["meta"] for item in brick_search["results"])
    with app.app_context():
        assert db.session.get(Representative, vacancy_id) is not None


def test_representative_remaining_tl_sums_open_product_targets(app):
    from app.extensions import db
    from app.models import IMSSummary, IMSUpload, Product, Representative, Target

    with app.app_context():
        representative = Representative(rep_code="DETAIL-GAP", rep_name="Açık Hedef Temsilcisi", active=True)
        over = Product(product_code="DETAIL-OVER", product_name="Hedef Üstü", display_order=1, is_active=True)
        under = Product(product_code="DETAIL-UNDER", product_name="Hedef Altı", display_order=2, is_active=True)
        upload = IMSUpload(file_name="detail-gap.xlsx", year=2026, month=1, quarter="Q1", status="COMPLETED")
        db.session.add_all((representative, over, under, upload))
        db.session.flush()
        db.session.add_all((
            Target(year=2026, month=1, quarter="Q1", representative_id=representative.id, product_id=over.id, tl_target=100, unit_target=1),
            Target(year=2026, month=1, quarter="Q1", representative_id=representative.id, product_id=under.id, tl_target=100, unit_target=1),
            IMSSummary(upload_id=upload.id, year=2026, month=1, quarter="Q1", representative_id=representative.id, product_id=over.id, tl=250, unit=1),
            IMSSummary(upload_id=upload.id, year=2026, month=1, quarter="Q1", representative_id=representative.id, product_id=under.id, tl=40, unit=1),
        ))
        db.session.commit()
        representative_id = representative.id

    client = app.test_client()
    client.post("/login", data={"email": "test@example.com", "password": "password123"})
    response = client.get(f"/representatives/view/{representative_id}?year=2026&month=1")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "290 ₺" in html
    assert "%145.0" in html
    assert "60 ₺" in html
    assert "Açık ürün hedefleri toplamı" in html


def test_ims_completed_status_is_rendered_in_turkish(app):
    from app.extensions import db
    from app.models import IMSUpload

    with app.app_context():
        db.session.add(IMSUpload(file_name="tamamlanan.xlsx", year=2026, month=8, status="COMPLETED"))
        db.session.commit()

    client = app.test_client()
    client.post("/login", data={"email": "test@example.com", "password": "password123"})
    response = client.get("/ims/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Tamamlandı" in html
    assert ">COMPLETED<" not in html


def test_ims_upload_time_is_rendered_in_istanbul_timezone(app):
    from datetime import datetime
    from app.extensions import db
    from app.models import IMSUpload

    with app.app_context():
        db.session.add(
            IMSUpload(
                file_name="saat-kontrol.xlsx",
                year=2026,
                month=8,
                status="COMPLETED",
                uploaded_at=datetime(2026, 8, 15, 10, 5),
            )
        )
        db.session.commit()

    client = app.test_client()
    client.post("/login", data={"email": "test@example.com", "password": "password123"})
    html = client.get("/ims/").get_data(as_text=True)

    assert "15.08.2026 13:05" in html


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


def test_manager_can_deactivate_and_transfer_period_work_area(app):
    from app.extensions import db
    from app.models import Representative, RepresentativeBrickAssignment, User

    with app.app_context():
        user = User.query.filter_by(email="test@example.com").one()
        user.role = "Admin"
        first = Representative(rep_code="AREA-1", rep_name="Alan Temsilcisi", active=True)
        second = Representative(rep_code="AREA-2", rep_name="Yeni Alan Temsilcisi", active=True)
        db.session.add_all([first, second])
        db.session.flush()
        assignment = RepresentativeBrickAssignment(
            representative_id=first.id, year=2026, month=8, quarter="Q3",
            brick="KADIKÖY MERKEZ", city="İstanbul", source="AUTO", active=True,
        )
        db.session.add(assignment)
        db.session.commit()
        first_id, second_id, assignment_id = first.id, second.id, assignment.id

    client = app.test_client()
    client.post("/login", data={"email": "test@example.com", "password": "password123"})
    page = client.get("/representatives/territory-management?year=2026&month=8")
    assert page.status_code == 200
    assert "KADIKÖY MERKEZ" in page.get_data(as_text=True)

    response = client.post(
        f"/representatives/territory-management/{assignment_id}/transfer",
        data={"target_representative_id": second_id}, follow_redirects=True,
    )
    assert response.status_code == 200
    with app.app_context():
        old = db.session.get(RepresentativeBrickAssignment, assignment_id)
        new = RepresentativeBrickAssignment.query.filter_by(
            representative_id=second_id, year=2026, month=8, brick="KADIKÖY MERKEZ"
        ).one()
        assert old.representative_id == first_id and old.active is False
        assert old.source == "MANUAL" and old.deactivated_at is not None
        assert new.active is True and new.source == "MANUAL"

    client.post(
        f"/representatives/territory-management/{new.id}/status",
        data={"active": "0", "reason": "İlçe çalışma kapsamından çıkarıldı"},
    )
    with app.app_context():
        assert db.session.get(RepresentativeBrickAssignment, new.id).active is False


def test_dashboard_repository_excludes_passive_work_areas(app):
    from app.extensions import db
    from app.models import Representative, RepresentativeBrickAssignment
    from app.repository.dashboard_repository import DashboardRepository

    with app.app_context():
        rep = Representative(rep_code="AREA-FILTER", rep_name="Filtre Temsilcisi", active=True)
        db.session.add(rep)
        db.session.flush()
        db.session.add_all([
            RepresentativeBrickAssignment(representative_id=rep.id, year=2026, month=8, brick="AKTİF BRICK", active=True),
            RepresentativeBrickAssignment(representative_id=rep.id, year=2026, month=8, brick="PASİF BRICK", active=False, source="MANUAL"),
        ])
        db.session.commit()
        rows = DashboardRepository(db.session).load_brick_assignments(2026, 8)
        assert [row.brick for row in rows] == ["AKTİF BRICK"]
