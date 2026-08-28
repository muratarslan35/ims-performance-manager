import tempfile
from datetime import datetime
from pathlib import Path

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


def test_representative_request_uses_assigned_brick_source_even_if_summary_is_zero():
    app, tmp = _app()
    try:
        with app.app_context():
            from app.extensions import db
            from app.models import IMSRawData, IMSSummary, IMSUpload, Product, Representative, RepresentativeBrickAssignment, Target
            from app.services.production_result_service import ProductionResultService

            db.create_all()
            rep = Representative(rep_name="ERHAN CENGIZ", region="901", city="MARDIN", active=True)
            product = Product(product_code="TRV", product_name="Travazol", display_order=1, is_active=True)
            db.session.add_all([rep, product]); db.session.flush()
            upload = IMSUpload(file_name="week8.xlsx", year=2026, month=2, week_number=8, status="COMPLETED", completed_at=datetime(2026, 2, 28))
            db.session.add(upload); db.session.flush()
            db.session.add_all([
                Target(year=2026, month=2, representative_id=rep.id, product_id=product.id, unit_target=100, tl_target=1000),
                IMSSummary(upload_id=upload.id, year=2026, month=2, representative_id=rep.id, product_id=product.id, unit=0, tl=0, bonus_amount=0),
                RepresentativeBrickAssignment(representative_id=rep.id, year=2026, month=2, brick="MARDIN MERKEZ+CEVRE ILC", active=True, source="AUTO"),
                IMSRawData(upload_id=upload.id, year=2026, month=2, week_number=8, sheet_name="Brick", sheet_type="brick_sales", source_row=2, representative_id=rep.id, product_id=product.id, brick="MARDIN MERKEZ+CEVRE ILC", unit=42, tl=420, raw_json="{}"),
            ])
            db.session.commit()

            with app.test_request_context(f"/representatives/view/{rep.id}?year=2026&month=2"):
                rows = ProductionResultService.effective_products(2026, 2, rep.id)
                row = rows[product.id]
                assert row["source"] == "IMS_BRICK"
                assert float(row["actual_unit"]) == 42.0
                assert float(row["actual_tl"]) == 420.0
                assert float(row["realization_percent"]) == 42.0
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
            event.listen(db.engine, "before_cursor_execute", lambda c, cur, stmt, p, ctx, many: statements.append(stmt))
            try:
                periods = RegionMarketService("901", [], 2026, 2)._available_periods()
            finally:
                event.remove(db.engine, "before_cursor_execute", event.listeners if False else None)
            assert periods == [{"year": 2026, "month": 2, "label": "02/2026"}]
            sql = " ".join(statements[-1].upper().split())
            assert "EXISTS" in sql
            assert "DISTINCT IMS_UPLOADS.YEAR" in sql
    finally:
        tmp.cleanup()
