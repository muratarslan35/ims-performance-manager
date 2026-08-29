from datetime import datetime
from pathlib import Path

from app import create_app


def _app(tmp_path):
    class Config:
        TESTING = True
        SECRET_KEY = "region-annual-official"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'region-annual-official.db'}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        LOGIN_DISABLED = True
        UPLOAD_FOLDER = Path(tmp_path) / "uploads"
        REPORT_FOLDER = Path(tmp_path) / "reports"
        BACKUP_FOLDER = Path(tmp_path) / "backups"
        LOG_FOLDER = Path(tmp_path) / "logs"
        TEMP_FOLDER = Path(tmp_path) / "temp"
    return create_app(Config)


def test_region_annual_chart_matches_official_monthly_region_realization(tmp_path):
    app = _app(tmp_path)
    from app.extensions import db
    from app.models import IMSRawData, IMSUpload, Product, Representative, Target
    from app.services.official_aggregate_service import TARGET_TYPE
    from app.services.region_performance_service import RegionPerformanceService

    with app.app_context():
        db.create_all()
        product = Product(product_code="CHART", product_name="Chart Product", is_active=True)
        rep = Representative(rep_code="CR1", rep_name="Chart Rep", region="901", city="Diyarbakır", active=True)
        db.session.add_all([product, rep])
        db.session.flush()
        upload = IMSUpload(
            file_name="week9.xlsx",
            year=2026,
            month=2,
            week_number=9,
            status="COMPLETED",
            completed_at=datetime(2026, 2, 28),
        )
        db.session.add(upload)
        db.session.flush()

        # Deliberately make the representative aggregate disagree with the
        # official region subtotal: legacy annual logic would display 40%.
        db.session.add(Target(
            year=2026,
            month=2,
            representative_id=rep.id,
            product_id=product.id,
            tl_target=1000,
            tl_realization=400,
            unit_target=10,
        ))
        db.session.add_all([
            IMSRawData(
                upload_id=upload.id,
                year=2026,
                month=2,
                sheet_name="BAKIYE",
                sheet_type=TARGET_TYPE,
                source_row=0,
                product_id=product.id,
                territory="901",
                unit=10,
                tl=1000,
                raw_json="{}",
            ),
            IMSRawData(
                upload_id=upload.id,
                year=2026,
                month=2,
                sheet_name="BAKIYE",
                sheet_type="dashboard_balance_region",
                source_row=0,
                product_id=product.id,
                territory="901",
                unit=2.5,
                tl=250,
                raw_json="{}",
            ),
        ])
        db.session.commit()

        report = RegionPerformanceService("901", 2026, 2).report()
        monthly = report["periods"]["monthly"]
        february = report["annual_realization"][1]

        assert float(monthly["realization_percent"]) == 75.0
        assert february["percent"] == 75.0
        assert february["target_tl"] == 1000.0
        assert february["actual_tl"] == 750.0
        assert february["source"] == "OFFICIAL_REGION_SUBTOTAL"
