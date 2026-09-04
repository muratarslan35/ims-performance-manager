from datetime import datetime
from pathlib import Path

from flask_migrate import upgrade

from app import create_app
from app.extensions import db
from app.models import (
    IMSSummary,
    IMSUpload,
    Product,
    ProductionResult,
    ProductionResultUpload,
    Representative,
    Target,
)
from app.services.annual_realization_service import AnnualRealizationService


MIGRATIONS_DIR = str(Path(__file__).resolve().parents[1] / "migrations")


def _app(tmp_path):
    class Config:
        TESTING = True
        SECRET_KEY = "annual-source-priority"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'annual-priority.db'}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = tmp_path / "uploads"
        REPORT_FOLDER = tmp_path / "reports"
        BACKUP_FOLDER = tmp_path / "backups"
        LOG_FOLDER = tmp_path / "logs"
        TEMP_FOLDER = tmp_path / "temp"

    application = create_app(Config)
    with application.app_context():
        upgrade(directory=MIGRATIONS_DIR)
    return application


def test_representative_annual_chart_prefers_production_then_ims_and_never_tl_fallback(tmp_path):
    application = _app(tmp_path)
    with application.app_context():
        rep = Representative(rep_code="ANNUAL1", rep_name="YILLIK TEMSILCI", active=True)
        product = Product(product_code="ANNUAL-P", product_name="Annual Product", is_active=True)
        db.session.add_all([rep, product])
        db.session.flush()

        for month in range(1, 6):
            db.session.add(Target(
                year=2026, month=month, representative_id=rep.id, product_id=product.id,
                tl_target=1000.0, tl_realization=400.0 if month == 5 else 999.0,
                unit_target=10.0,
            ))

        # January-March accepted production must supersede any IMS/persisted TL.
        stages = [(1, 2, 120.0), (2, 1, 90.0), (3, 2, 80.0)]
        for month, stage, realization in stages:
            upload = ProductionResultUpload(
                file_name=f"p{stage}-{month}.xlsx", stored_file_name=f"p{stage}-{month}.xlsx",
                source_hash=(str(month) * 64)[:64], year=2026, month=month,
                production_stage=stage, status=ProductionResultUpload.STATUS_APPLIED,
                applied_at=datetime(2026, month, 20, 8, 0),
            )
            db.session.add(upload)
            db.session.flush()
            db.session.add(ProductionResult(
                upload_id=upload.id, representative_id=rep.id,
                product_id=product.id, realization_percent=realization,
            ))

        # April has no production yet: IMS is authoritative and must beat persisted TL=999.
        ims_upload = IMSUpload(file_name="week16.xlsx", year=2026, month=4, status="COMPLETED")
        db.session.add(ims_upload)
        db.session.flush()
        db.session.add(IMSSummary(
            upload_id=ims_upload.id, year=2026, month=4,
            representative_id=rep.id, product_id=product.id,
            tl=600.0, unit=6.0, target_tl=1000.0, target_unit=10.0,
        ))
        db.session.commit()

        rows = AnnualRealizationService.build(2026, [rep.id])

        assert rows[0]["actual_tl"] == 1200.0 and rows[0]["percent"] == 120.0
        assert rows[0]["source"] == "PRODUCTION_2"
        assert rows[1]["actual_tl"] == 900.0 and rows[1]["source"] == "PRODUCTION_1"
        assert rows[2]["actual_tl"] == 800.0 and rows[2]["source"] == "PRODUCTION_2"
        assert rows[3]["actual_tl"] == 600.0 and rows[3]["percent"] == 60.0
        assert rows[3]["source"] == "IMS"

        # May has a Target row but no IMS or production source. It must stay absent
        # instead of using Target.tl_realization as a fabricated fallback point.
        assert rows[4]["actual_tl"] == 0.0
        assert rows[4]["target_tl"] == 0.0
        assert rows[4]["percent"] is None
        assert rows[4]["has_data"] is False
        assert rows[4]["source"] is None
