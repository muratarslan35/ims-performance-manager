from io import BytesIO
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from openpyxl import load_workbook

from app.extensions import db
from app.models import Product, Representative, RepresentativeBrickAssignment, User
from werkzeug.security import generate_password_hash
from app.services.executive_reporting_service import ExecutiveReportingService
from app.services.persistent_representative_snapshot_service import PersistentRepresentativeSnapshotService
from app.services.report_cache_service import ReportCacheService
from app.services.report_export_queue import ReportExportQueue


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
        REPORT_CACHE_FOLDER = tmp_path / "report_cache"
        REPORT_EXPORT_QUEUE_FOLDER = tmp_path / "report_export_queue"

    application = create_app(Config)
    with application.app_context():
        db.create_all()
    yield application


def _snapshot(product_id, target=100, actual=80, unit=40, market=100, product_name="Travazol", brick="BRICK A"):
    return {"snapshots": {"monthly": {
        "products": [{
            "product": {"id": product_id}, "target_tl": target, "actual_tl": actual,
            "target_unit": 50, "actual_unit": unit,
        }],
        "market_analysis": {
            "source_week": 36,
            "rows": [{
                "product_id": product_id, "market_unit": market,
                "rivals": [{"name": "Rakip A", "unit": market - unit}],
            }],
            "brick_product_rows": [{
                "brick": brick,
                "product_name": product_name,
                "company_unit": unit,
                "competitor_unit": market - unit,
                "market_unit": market,
                "market_products": [
                    {"name": product_name, "unit": unit, "is_company": True},
                    {"name": "Rakip A", "unit": market - unit, "is_company": False},
                ],
            }],
        },
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


def test_scope_options_use_region_names_and_real_assignment_cities(app):
    with app.app_context():
        first = Representative(
            rep_code="RPT-901-A", rep_name="Mardin Temsilcisi",
            region="901", city="DIYARBAKIR", active=True,
        )
        second = Representative(
            rep_code="RPT-901-B", rep_name="Şırnak Temsilcisi",
            region="901 DIYARBAKIR", city="DIYARBAKIR", active=True,
        )
        db.session.add_all([first, second])
        db.session.flush()
        db.session.add_all([
            RepresentativeBrickAssignment(
                representative_id=first.id, year=2026, month=9, quarter="Q3",
                brick="MARDIN BRICK", city="MARDIN", source="AUTO", active=True,
            ),
            RepresentativeBrickAssignment(
                representative_id=second.id, year=2026, month=9, quarter="Q3",
                brick="SIRNAK BRICK", city="ŞIRNAK", source="AUTO", active=True,
            ),
        ])
        db.session.commit()

        service = ExecutiveReportingService(year=2026, month=9, scope="region", scope_value="901")
        options = service.filter_options()
        assert {"value": "901", "label": "Diyarbakır"} in options["regions"]
        assert [item["value"] for item in options["cities"]] == ["MARDIN", "ŞIRNAK"]
        assert {row.id for row in service._representatives()} == {first.id, second.id}

        city_service = ExecutiveReportingService(
            year=2026, month=9, scope="city", scope_value="MARDIN"
        )
        assert [row.id for row in city_service._representatives()] == [first.id]
        assert city_service.scope_label() == "MARDIN"


def test_multi_scope_regions_and_product_filter_build_only_selected_product(app, monkeypatch):
    with app.app_context():
        rep_a = Representative(
            rep_code="RPT-MULTI-A", rep_name="Diyarbakır Rep",
            region="901", city="DIYARBAKIR", active=True,
        )
        rep_b = Representative(
            rep_code="RPT-MULTI-B", rep_name="Adana Rep",
            region="701", city="ADANA", active=True,
        )
        rep_c = Representative(
            rep_code="RPT-MULTI-C", rep_name="Ankara Rep",
            region="501", city="ANKARA", active=True,
        )
        monurol = Product(
            product_code="RPT-MONUROL", product_name="Monurol",
            display_order=1, is_active=True,
        )
        travazol = Product(
            product_code="RPT-TRAVAZOL", product_name="Travazol",
            display_order=2, is_active=True,
        )
        db.session.add_all([rep_a, rep_b, rep_c, monurol, travazol])
        db.session.commit()

        def active_many(cls, representative_ids, year, month):
            assert set(representative_ids) == {rep_a.id, rep_b.id}
            return {
                rep_a.id: _snapshot(
                    monurol.id, target=200, actual=100, unit=20, market=50,
                    product_name="Monurol", brick="DIYARBAKIR BRICK",
                ),
                rep_b.id: _snapshot(
                    monurol.id, target=300, actual=150, unit=30, market=70,
                    product_name="Monurol", brick="ADANA BRICK",
                ),
            }

        monkeypatch.setattr(
            PersistentRepresentativeSnapshotService,
            "get_active_many",
            classmethod(active_many),
        )
        service = ExecutiveReportingService(
            year=2026, month=9, scope="region",
            scope_values=["901", "701"], product_ids=[monurol.id],
        )
        report = service.build()

        assert set(report["scope_values"]) == {"901", "701"}
        assert report["scope_label"] == "Adana + Diyarbakır"
        assert report["representative_count"] == 2
        assert [row["product_name"] for row in report["rows"]] == ["Monurol"]
        assert report["rows"][0]["actual_unit"] == 50
        assert {row["representative_name"] for row in report["representative_rows"]} == {
            "Diyarbakır Rep", "Adana Rep",
        }
        assert {row["region_name"] for row in report["region_rows"]} == {
            "Diyarbakır", "Adana",
        }
        assert {row["brick"] for row in report["brick_rows"]} == {
            "DIYARBAKIR BRICK", "ADANA BRICK",
        }


def test_multi_city_and_representative_scope_filters(app):
    with app.app_context():
        reps = [
            Representative(
                rep_code="RPT-CITY-1", rep_name="Mardin Rep",
                region="901", city="DIYARBAKIR", active=True,
            ),
            Representative(
                rep_code="RPT-CITY-2", rep_name="Şırnak Rep",
                region="901", city="DIYARBAKIR", active=True,
            ),
            Representative(
                rep_code="RPT-CITY-3", rep_name="Adana Rep",
                region="701", city="ADANA", active=True,
            ),
        ]
        db.session.add_all(reps)
        db.session.flush()
        db.session.add_all([
            RepresentativeBrickAssignment(
                representative_id=reps[0].id, year=2026, month=9, quarter="Q3",
                brick="MARDIN B", city="MARDIN", source="AUTO", active=True,
            ),
            RepresentativeBrickAssignment(
                representative_id=reps[1].id, year=2026, month=9, quarter="Q3",
                brick="SIRNAK B", city="ŞIRNAK", source="AUTO", active=True,
            ),
            RepresentativeBrickAssignment(
                representative_id=reps[2].id, year=2026, month=9, quarter="Q3",
                brick="ADANA B", city="ADANA", source="AUTO", active=True,
            ),
        ])
        db.session.commit()

        city_service = ExecutiveReportingService(
            year=2026, month=9, scope="city", scope_values=["MARDIN", "ŞIRNAK"]
        )
        assert {row.id for row in city_service._representatives()} == {
            reps[0].id, reps[1].id,
        }

        rep_service = ExecutiveReportingService(
            year=2026, month=9, scope="representative",
            scope_values=[str(reps[0].id), str(reps[2].id)],
        )
        assert {row.id for row in rep_service._representatives()} == {
            reps[0].id, reps[2].id,
        }
        assert rep_service.scope_label() == "Mardin Rep + Adana Rep"


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
        assert report["scope_label"] == "İstanbul"
        assert report["source_week"] == 36
        assert [row["product_name"] for row in report["rows"]] == ["Travazol"]
        assert report["rows"][0]["realization_percent"] == 80
        assert report["rows"][0]["market_share_percent"] == 40.0
        assert report["rows"][0]["rivals"] == [{"name": "Rakip A", "unit": 60.0, "share_percent": 60.0}]
        assert report["rival_rows"][0]["share_percent"] == 60.0

        workbook = load_workbook(BytesIO(service.to_excel(report).getvalue()))
        assert workbook.active["A1"].value == "SATIŞ VE PAZAR PERFORMANS RAPORU"
        assert workbook.active["A9"].value == "Travazol"
        assert workbook.sheetnames == [
            "Yönetim Özeti", "Dönem Trendi", "Bölge Analizi",
            "Temsilci Analizi", "Brick Analizi", "Rakip Analizi",
        ]
        assert workbook["Rakip Analizi"]["D5"].value == 0.6
        assert workbook["Temsilci Analizi"]["C5"].value == "Rapor Temsilcisi"
        assert workbook["Brick Analizi"]["D5"].value == "BRICK A"
        pdf = service.to_pdf(report).getvalue()
        assert pdf.startswith(b"%PDF-")
        assert pdf.count(b"/Type /Page") >= 2


def test_reports_navigation_is_visible_with_direct_reports_name():
    sidebar = open("app/templates/partials/sidebar.html", encoding="utf-8").read()
    template = open("app/templates/reports.html", encoding="utf-8").read()
    css = open("app/static/css/style.css", encoding="utf-8").read()
    assert '<span class="sidebar-nav-label">Raporlar</span>' in sidebar
    assert "Genel Müdür Raporları" not in sidebar
    assert "{% block styles %}" in template
    assert "executive-reports.css" in template
    assert "{% block head %}" not in template
    assert 'data-page-loader="false"' in template
    assert 'class="btn btn-success report-export" data-page-loader="false" download' in template
    report_js = open("app/static/js/executive-reports.js", encoding="utf-8").read()
    layout_js = open("app/static/js/layout.js", encoding="utf-8").read()
    assert "fetch(url" in report_js
    assert "window.location.href" not in report_js
    assert "anchor.dataset.pageLoader === 'false'" in layout_js
    assert "row.rivals[:3]" not in template
    assert 'name="scope_value"' in template
    assert 'data-scope-panel="region"' in template
    assert 'data-scope-panel="city"' in template
    assert 'data-scope-panel="representative"' in template
    assert "TEMSİLCİ ANALİZİ" in template
    assert "BRICK ANALİZİ" in template
    assert 'a[href="/reports"]' not in css


def test_admin_report_exports_are_queued_then_served_from_cached_artifact(app):
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
    assert "Satış ve pazar performansı" in page.get_data(as_text=True)

    for file_type, prefix in (("xlsx", b"PK"), ("pdf", b"%PDF-")):
        queued = client.get(
            f"/reports/export/{file_type}?year=2026&month=8&period=monthly&scope=national"
        )
        assert queued.status_code == 202
        payload = queued.get_json()
        assert payload["status"] == "QUEUED"

        with app.app_context():
            job = ReportExportQueue.read(payload["job_id"])
            report = ReportCacheService.read_by_key(job["cache_key"])
            service = ExecutiveReportingService(
                year=report["year"], month=report["month"],
                period=report["period"], scope=report["scope"],
            )
            output = service.to_excel(report) if file_type == "xlsx" else service.to_pdf(report)
            ReportCacheService.write_export(job["cache_key"], file_type, output.getvalue())
            ReportExportQueue.complete(job)

        status = client.get(payload["status_url"])
        assert status.status_code == 200
        status_payload = status.get_json()
        assert status_payload["status"] == "COMPLETED"
        downloaded = client.get(status_payload["download_url"])
        assert downloaded.status_code == 200
        assert downloaded.data.startswith(prefix)
        assert f"national-analiz-raporu-2026-08.{file_type}" in downloaded.headers["Content-Disposition"]

        # A second request for the same source/filter combination is an
        # immediate cached file response; no new PDF/XLSX work is queued.
        cached = client.get(
            f"/reports/export/{file_type}?year=2026&month=8&period=monthly&scope=national"
        )
        assert cached.status_code == 200
        assert cached.data.startswith(prefix)


def test_export_filenames_follow_selected_scope(app):
    with app.app_context():
        rep = Representative(
            rep_code="RPT-NAME", rep_name="Murat Arslan",
            region="901", city="DIYARBAKIR", active=True,
        )
        db.session.add(rep)
        db.session.commit()
        representative = ExecutiveReportingService(
            year=2026, month=9, scope="representative", scope_value=str(rep.id)
        )
        region = ExecutiveReportingService(
            year=2026, month=9, scope="region", scope_value="901"
        )
        city = ExecutiveReportingService(
            year=2026, month=9, scope="city", scope_value="MARDIN"
        )

        assert representative.export_filename(
            {"scope_label": "Murat Arslan", "year": 2026, "month": 9}, "pdf"
        ) == "temsilci-analiz-raporu-murat-arslan-2026-09.pdf"
        assert region.export_filename(
            {"scope_label": "Diyarbakır", "year": 2026, "month": 9}, "xlsx"
        ) == "bolge-analiz-raporu-diyarbakir-2026-09.xlsx"
        assert city.export_filename(
            {"scope_label": "MARDIN", "year": 2026, "month": 9}, "pdf"
        ) == "il-analiz-raporu-mardin-2026-09.pdf"
