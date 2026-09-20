from io import BytesIO
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from openpyxl import load_workbook

from app.extensions import db
from app.models import Product, Representative, User
from werkzeug.security import generate_password_hash
from app.services.executive_reporting_service import ExecutiveReportingService
from app.services.persistent_representative_snapshot_service import PersistentRepresentativeSnapshotService


@pytest.fixture()
def app(tmp_path):
    from app import create_app

    class Config:
        TESTING = True
        SECRET_KEY = "report-test"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'reports.db'}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = tmp_path / "uploads"
        REPORT_FOLDER = tmp_path / "reports"
        BACKUP_FOLDER = tmp_path / "backups"
        LOG_FOLDER = tmp_path / "logs"
        TEMP_FOLDER = tmp_path / "temp"

    application = create_app(Config)
    with application.app_context():
        db.create_all()
    yield application


def _snapshot(product_id, target=100, actual=80, unit=40, market=100):
    return {"snapshots": {"monthly": {
        "products": [{
            "product": {"id": product_id}, "target_tl": target, "actual_tl": actual,
            "target_unit": 50, "actual_unit": unit,
        }],
        "market_analysis": {"source_week": 36, "rows": [{
            "product_id": product_id, "market_unit": market,
            "rivals": [{"name": "Rakip A", "unit": market - unit}],
        }]},
    }}}


def test_period_contracts_keep_fixed_h1_and_trailing_three_months(app):
    with app.app_context():
        assert ExecutiveReportingService(year=2026, month=9, period="quarterly").months() == [
            (2026, 7), (2026, 8), (2026, 9),
        ]
        assert ExecutiveReportingService(year=2026, month=9, period="half_year").months() == [
            (2026, month) for month in range(1, 7)
        ]
        assert ExecutiveReportingService(year=2026, month=9, period="yearly").months() == [
            (2026, month) for month in range(1, 10)
        ]


def test_snapshot_only_report_filters_scope_product_and_exports(app, monkeypatch):
    with app.app_context():
        rep = Representative(rep_code="RPT-1", rep_name="Rapor Temsilcisi", region="101 TEST", city="ANKARA", active=True)
        selected = Product(product_code="RPT-P1", product_name="Travazol", display_order=1, is_active=True)
        ignored = Product(product_code="RPT-P2", product_name="Monurol", display_order=2, is_active=True)
        db.session.add_all([rep, selected, ignored]); db.session.commit()

        def active_many(cls, representative_ids, year, month):
            assert representative_ids == [rep.id]
            return {rep.id: _snapshot(selected.id)}

        monkeypatch.setattr(PersistentRepresentativeSnapshotService, "get_active_many", classmethod(active_many))
        service = ExecutiveReportingService(
            year=2026, month=8, period="monthly", scope="region", scope_value="101 TEST",
            product_ids=[selected.id],
        )
        report = service.build()
        assert report["scope_label"] == "101 TEST"
        assert report["source_week"] == 36
        assert [row["product_name"] for row in report["rows"]] == ["Travazol"]
        assert report["rows"][0]["realization_percent"] == 80
        assert report["rows"][0]["market_share_percent"] == 40.0
        assert report["rows"][0]["rivals"] == [{"name": "Rakip A", "unit": 60.0}]

        workbook = load_workbook(BytesIO(service.to_excel(report).getvalue()))
        assert workbook.active["A1"].value == "GENEL MÜDÜR PAZAR RAPORU"
        assert workbook.active["A5"].value == "Travazol"
        assert service.to_pdf(report).getvalue().startswith(b"%PDF-1.4")


def test_reports_navigation_is_a_visible_dedicated_section():
    sidebar = open("app/templates/partials/sidebar.html", encoding="utf-8").read()
    css = open("app/static/css/style.css", encoding="utf-8").read()
    assert '<li class="sidebar-section-label">Raporlar</li>' in sidebar
    assert "Genel Müdür Raporları" in sidebar
    assert 'a[href="/reports"]' not in css


def test_admin_can_render_reports_and_download_both_formats(app):
    with app.app_context():
        db.session.add(User(
            full_name="Murat Arslan", email="admin@example.com", role="Admin", active=True,
            password=generate_password_hash("password123"),
        ))
        db.session.commit()
    client = app.test_client()
    response = client.post("/login", data={"email": "admin@example.com", "password": "password123"})
    assert response.status_code in {302, 303}
    page = client.get("/reports?year=2026&month=8&period=monthly&scope=national")
    assert page.status_code == 200
    assert "Genel Müdür Raporları" in page.get_data(as_text=True)
    excel = client.get("/reports/export/xlsx?year=2026&month=8&period=monthly&scope=national")
    pdf = client.get("/reports/export/pdf?year=2026&month=8&period=monthly&scope=national")
    assert excel.status_code == 200 and excel.data.startswith(b"PK")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF-1.4")
