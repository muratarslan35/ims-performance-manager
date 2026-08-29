from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app import create_app


def _app(tmp_path):
    class Config:
        TESTING = True
        SECRET_KEY = "region-read-v2"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'region-read-v2.db'}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        LOGIN_DISABLED = True
        UPLOAD_FOLDER = Path(tmp_path) / "uploads"
        REPORT_FOLDER = Path(tmp_path) / "reports"
        BACKUP_FOLDER = Path(tmp_path) / "backups"
        LOG_FOLDER = Path(tmp_path) / "logs"
        TEMP_FOLDER = Path(tmp_path) / "temp"
    return create_app(Config)


def test_region_uses_official_target_minus_balance_when_weekly_actual_missing(tmp_path):
    app = _app(tmp_path)
    from app.extensions import db
    from app.models import IMSRawData, IMSUpload, Product, Representative, Target
    from app.services.official_aggregate_service import TARGET_TYPE
    from app.services.region_performance_service import RegionPerformanceService

    with app.app_context():
        db.create_all()
        product = Product(product_code="R8", product_name="Region 8", is_active=True)
        rep = Representative(rep_code="R901", rep_name="Region Rep", region="901", city="Diyarbakır", active=True)
        db.session.add_all([product, rep]); db.session.flush()
        upload = IMSUpload(file_name="week8.xlsx", year=2026, month=2, week_number=8, status="COMPLETED", completed_at=datetime(2026, 2, 28))
        db.session.add(upload); db.session.flush()
        db.session.add(Target(year=2026, month=2, representative_id=rep.id, product_id=product.id, tl_target=1200, unit_target=12))
        db.session.add_all([
            IMSRawData(upload_id=upload.id, year=2026, month=2, sheet_name="BAKIYE", sheet_type=TARGET_TYPE, source_row=0, product_id=product.id, territory="901", unit=12, tl=1200, raw_json="{}"),
            IMSRawData(upload_id=upload.id, year=2026, month=2, sheet_name="BAKIYE", sheet_type="dashboard_balance_region", source_row=0, product_id=product.id, territory="901", unit=1200, tl=300, raw_json="{}"),
        ])
        db.session.commit()
        monthly = RegionPerformanceService("901", 2026, 2).report()["periods"]["monthly"]
        assert monthly["complete"] is True
        assert monthly["target_tl"] == Decimal("1200.0")
        assert monthly["actual_tl"] == Decimal("900.0")
        assert monthly["realization_percent"] == Decimal("75.00")


def test_representative_period_prefers_persisted_ims_actual_over_corrupt_summary(tmp_path):
    app = _app(tmp_path)
    from app.extensions import db
    from app.models import IMSSummary, IMSUpload, Product, Representative, Target
    from app.services.representative_period_snapshot_service import RepresentativePeriodSnapshotService

    with app.app_context():
        db.create_all()
        product = Product(product_code="W8", product_name="Week8", is_active=True)
        rep = Representative(rep_code="W8R", rep_name="Week8 Rep", active=True)
        db.session.add_all([product, rep]); db.session.flush()
        upload = IMSUpload(file_name="week8.xlsx", year=2026, month=2, week_number=8, status="COMPLETED")
        db.session.add(upload); db.session.flush()
        db.session.add(Target(year=2026, month=2, representative_id=rep.id, product_id=product.id, tl_target=1000, unit_target=10, tl_realization=250, unit_realization=2))
        db.session.add(IMSSummary(upload_id=upload.id, year=2026, month=2, representative_id=rep.id, product_id=product.id, tl=0, unit=999999))
        db.session.commit()
        monthly = RepresentativePeriodSnapshotService.build(rep.id, 2026, 2)["monthly"]
        assert monthly["complete"] is True
        assert monthly["actual_tl"] == Decimal("250")
        assert monthly["realization_percent"] == 25.0


def test_representative_period_preserves_legacy_summary_when_target_actual_unset(tmp_path):
    app = _app(tmp_path)
    from app.extensions import db
    from app.models import IMSSummary, IMSUpload, Product, Representative, Target
    from app.services.representative_period_snapshot_service import RepresentativePeriodSnapshotService

    with app.app_context():
        db.create_all()
        product = Product(product_code="OLD", product_name="Legacy", is_active=True)
        rep = Representative(rep_code="OLDR", rep_name="Legacy Rep", active=True)
        db.session.add_all([product, rep]); db.session.flush()
        upload = IMSUpload(file_name="old.xlsx", year=2025, month=12, status="COMPLETED")
        db.session.add(upload); db.session.flush()
        db.session.add(Target(year=2025, month=12, representative_id=rep.id, product_id=product.id, tl_target=1000, unit_target=10, tl_realization=0))
        db.session.add(IMSSummary(upload_id=upload.id, year=2025, month=12, representative_id=rep.id, product_id=product.id, tl=600, unit=6))
        db.session.commit()
        monthly = RepresentativePeriodSnapshotService.build(rep.id, 2025, 12)["monthly"]
        assert monthly["actual_tl"] == Decimal("600.0")
        assert monthly["realization_percent"] == 60.0


def test_annual_realization_prefers_persisted_target_actual(tmp_path):
    app = _app(tmp_path)
    from app.extensions import db
    from app.models import IMSSummary, IMSUpload, Product, Representative, Target
    from app.services.annual_realization_service import AnnualRealizationService

    with app.app_context():
        db.create_all()
        product = Product(product_code="ANN", product_name="Annual", is_active=True)
        rep = Representative(rep_code="ANNR", rep_name="Annual Rep", active=True)
        db.session.add_all([product, rep]); db.session.flush()
        upload = IMSUpload(file_name="annual.xlsx", year=2026, month=2, status="COMPLETED")
        db.session.add(upload); db.session.flush()
        db.session.add(Target(year=2026, month=2, representative_id=rep.id, product_id=product.id, tl_target=1000, tl_realization=400))
        db.session.add(IMSSummary(upload_id=upload.id, year=2026, month=2, representative_id=rep.id, product_id=product.id, tl=0, unit=9999))
        db.session.commit()
        february = AnnualRealizationService.build(2026, [rep.id])[1]
        assert february["actual_tl"] == 400.0
        assert february["percent"] == 40.0


def test_region_rolling_periods_use_latest_completed_ims_while_monthly_keeps_selection(monkeypatch):
    from app.services.region_performance_service import RegionPerformanceService
    service = object.__new__(RegionPerformanceService)
    service.year = 2026
    service.month = 1
    monkeypatch.setattr(service, "_latest_completed_period", lambda: (2026, 2))
    assert service.period_months(1) == [(2026, 1)]
    assert service.period_months(3) == [(2025, 12), (2026, 1), (2026, 2)]
    assert service.period_months(6) == [(2025, 9), (2025, 10), (2025, 11), (2025, 12), (2026, 1), (2026, 2)]
    assert service.period_months(None) == [(2026, 1), (2026, 2)]
