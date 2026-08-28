import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import event


def _app():
    from app import create_app

    tmp = tempfile.TemporaryDirectory()
    db_path = Path(tmp.name) / "field-read.db"

    class TestConfig:
        TESTING = True
        SECRET_KEY = "field-read-test"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        LOGIN_DISABLED = True
        UPLOAD_FOLDER = Path(tmp.name) / "uploads"
        REPORT_FOLDER = Path(tmp.name) / "reports"
        BACKUP_FOLDER = Path(tmp.name) / "backups"
        LOG_FOLDER = Path(tmp.name) / "logs"
        TEMP_FOLDER = Path(tmp.name) / "temp"

    return create_app(TestConfig), tmp


def test_completed_ims_uses_target_realization_not_corrupted_summary_on_representative_detail():
    app, tmp = _app()
    try:
        with app.app_context():
            from app.extensions import db
            from app.models import IMSSummary, IMSUpload, Product, Representative, Target
            from app.services.production_result_service import ProductionResultService

            db.create_all()
            rep = Representative(rep_name="MURAT ARSLAN", region="901", city="DIYARBAKIR", active=True)
            product = Product(product_code="TRV", product_name="Travazol", display_order=1, is_active=True)
            db.session.add_all([rep, product]); db.session.flush()
            upload = IMSUpload(
                file_name="week8.xlsx", year=2026, month=2, week_number=8,
                status="COMPLETED", completed_at=datetime(2026, 2, 28),
            )
            db.session.add(upload); db.session.flush()
            target = Target(
                year=2026, month=2, representative_id=rep.id, product_id=product.id,
                unit_target=8991, tl_target=1003918,
                unit_realization=859, tl_realization=73689,
            )
            corrupted = IMSSummary(
                upload_id=upload.id, year=2026, month=2,
                representative_id=rep.id, product_id=product.id,
                unit=4298766.48, tl=0, bonus_amount=0,
            )
            db.session.add_all([target, corrupted]); db.session.commit()

            with app.test_request_context(f"/representatives/view/{rep.id}?year=2026&month=2"):
                rows = ProductionResultService.effective_products(2026, 2, rep.id)
                row = rows[product.id]
                assert row["source"] == "IMS"
                assert row["complete"] is True
                assert float(row["actual_unit"]) == 859.0
                assert float(row["actual_tl"]) == 73689.0
                assert round(float(row["realization_percent"]), 4) == round(73689 * 100 / 1003918, 4)
    finally:
        tmp.cleanup()


def test_completed_ims_preserves_real_zero_target_realization_on_region_detail():
    app, tmp = _app()
    try:
        with app.app_context():
            from app.extensions import db
            from app.models import IMSUpload, Product, Representative, Target
            from app.services.production_result_service import ProductionResultService

            db.create_all()
            rep = Representative(rep_name="ZERO REP", active=True)
            product = Product(product_code="ZERO", product_name="Zero Product", is_active=True)
            db.session.add_all([rep, product]); db.session.flush()
            db.session.add(IMSUpload(file_name="zero.xlsx", year=2026, month=3, week_number=1, status="COMPLETED"))
            db.session.add(Target(
                year=2026, month=3, representative_id=rep.id, product_id=product.id,
                unit_target=10, tl_target=1000, unit_realization=0, tl_realization=0,
            ))
            db.session.commit()

            with app.test_request_context("/regions/901?year=2026&month=3"):
                row = ProductionResultService.effective_products(2026, 3, rep.id)[product.id]
                assert row["source"] == "IMS"
                assert row["complete"] is True
                assert float(row["actual_unit"]) == 0.0
                assert float(row["actual_tl"]) == 0.0
    finally:
        tmp.cleanup()


def test_non_field_services_keep_existing_summary_source():
    app, tmp = _app()
    try:
        with app.app_context():
            from app.extensions import db
            from app.models import IMSSummary, IMSUpload, Product, Representative, Target
            from app.services.production_result_service import ProductionResultService

            db.create_all()
            rep = Representative(rep_name="LEGACY REP", active=True)
            product = Product(product_code="LEG", product_name="Legacy Product", is_active=True)
            db.session.add_all([rep, product]); db.session.flush()
            upload = IMSUpload(file_name="legacy.xlsx", year=2025, month=6, status="COMPLETED")
            db.session.add(upload); db.session.flush()
            db.session.add_all([
                Target(year=2025, month=6, representative_id=rep.id, product_id=product.id, tl_target=1000, unit_target=10),
                IMSSummary(upload_id=upload.id, year=2025, month=6, representative_id=rep.id, product_id=product.id, tl=950, unit=9),
            ])
            db.session.commit()
            row = ProductionResultService.effective_products(2025, 6, rep.id)[product.id]
            assert float(row["actual_tl"]) == 950.0
            assert float(row["actual_unit"]) == 9.0
    finally:
        tmp.cleanup()


def test_region_period_discovery_is_upload_centered_exists_query():
    app, tmp = _app()
    try:
        with app.app_context():
            from app.extensions import db
            from app.models import CompetitionData, IMSUpload
            from app.services.region_market_service import RegionMarketService

            db.create_all()
            upload = IMSUpload(file_name="week8.xlsx", year=2026, month=2, week_number=8, status="COMPLETED", completed_at=datetime(2026, 2, 28))
            db.session.add(upload); db.session.flush()
            db.session.add(CompetitionData(
                upload_id=upload.id, year=2026, month=2, week_number=8, sheet_name="AYLIK REKABET KUTU",
                period_type="MONTHLY", territory="901", subterritory="MARDIN MERKEZ", product_group="TRAVAZOL",
                product_name="RIVAL", metric_type="UNIT", metric_value=10, source_row=1,
                is_subtotal=False, is_grand_total=False,
            ))
            db.session.commit()
            statements = []

            def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
                statements.append(statement)

            event.listen(db.engine, "before_cursor_execute", capture)
            try:
                periods = RegionMarketService("901", [], 2026, 2)._available_periods()
            finally:
                event.remove(db.engine, "before_cursor_execute", capture)
            assert periods == [{"year": 2026, "month": 2, "label": "02/2026"}]
            sql = " ".join(statements[-1].upper().split())
            assert "EXISTS" in sql
            assert "DISTINCT IMS_UPLOADS.YEAR" in sql
    finally:
        tmp.cleanup()


def test_competitor_ai_hides_period_dimension_without_changing_real_products():
    app, tmp = _app()
    try:
        with app.app_context():
            from app.services.dashboard_service import DashboardService

            rows = [
                SimpleNamespace(product_name="FEB 2026", product_group="MONTH", territory="101 ISTANBUL", sales_tl=999999),
                SimpleNamespace(product_name="UROCARE", product_group="MONUROL GRUBU", territory="901 DIYARBAKIR", sales_tl=1250),
            ]
            result = DashboardService._competitor_ai(rows, [])
            assert [item["product_name"] for item in result["top_products"]] == ["UROCARE"]
            assert [item["product_name"] for item in result["hot_regions"]] == ["UROCARE"]
    finally:
        tmp.cleanup()
