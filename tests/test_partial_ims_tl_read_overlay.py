from datetime import datetime
from pathlib import Path

from flask_migrate import upgrade

from app import create_app
from app.extensions import db
from app.models import IMSRawData, IMSSummary, IMSUpload, Product, Representative, Target
from app.query.dashboard_query import DashboardQuery
from app.query.filters import DashboardFilterParams
from app.services.official_aggregate_service import ACTUAL_TYPE, TARGET_TYPE, OfficialAggregateService
from app.services.region_performance_service import RegionPerformanceService


MIGRATIONS_DIR = str(Path(__file__).resolve().parents[1] / "migrations")


def _app(tmp_path):
    class Config:
        TESTING = True
        SECRET_KEY = "partial-overlay-test"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'partial-overlay.db'}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = tmp_path / "uploads"
        REPORT_FOLDER = tmp_path / "reports"
        BACKUP_FOLDER = tmp_path / "backups"
        LOG_FOLDER = tmp_path / "logs"
        TEMP_FOLDER = tmp_path / "temp"

    app = create_app(Config)
    with app.app_context():
        upgrade(directory=MIGRATIONS_DIR)
    return app


def _seed():
    product = Product(product_code="OVERLAY", product_name="Overlay Product", is_active=True)
    rep = Representative(
        rep_code="OVERLAY-901", rep_name="OVERLAY REP", region="901", city="DIYARBAKIR", active=True
    )
    db.session.add_all([product, rep]); db.session.flush()

    old = IMSUpload(
        file_name="week11.xlsx", year=2041, month=3, quarter="Q1", week_number=11,
        status="COMPLETED", reconciliation_status="PASSED", summary_record_count=1,
        completed_at=datetime(2041, 3, 18, 8, 0),
    )
    latest = IMSUpload(
        file_name="week13-compact.xlsx", year=2041, month=3, quarter="Q1", week_number=13,
        status="COMPLETED", reconciliation_status="PASSED", summary_record_count=1,
        completed_at=datetime(2041, 3, 25, 8, 0),
    )
    db.session.add_all([old, latest]); db.session.flush()

    for territory, representative in (("NATIONAL", "NATIONAL"), ("901", "901 DIYARBAKIR")):
        db.session.add(IMSRawData(
            upload_id=old.id, year=2041, month=3, quarter="Q1", week_number=11,
            sheet_name="BAKIYE", sheet_type=TARGET_TYPE, source_row=0,
            product_id=product.id, representative=representative, territory=territory,
            unit=20.0, tl=100.0, raw_json="{}",
        ))
        db.session.add(IMSRawData(
            upload_id=old.id, year=2041, month=3, quarter="Q1", week_number=11,
            sheet_name="TTS HAFTALIK CIKISLARI", sheet_type=ACTUAL_TYPE, source_row=0,
            product_id=product.id, representative=representative, territory=territory,
            unit=10.0, tl=50.0, raw_json="{}",
        ))

    db.session.add(Target(
        year=2041, month=3, quarter="Q1", representative_id=rep.id, product_id=product.id,
        tl_target=200.0, unit_target=0.0,
    ))
    summary = IMSSummary(
        upload_id=latest.id, year=2041, month=3, quarter="Q1",
        representative_id=rep.id, product_id=product.id,
        target_tl=200.0, target_unit=0.0, tl=150.0, unit=999.0,
    )
    db.session.add(summary); db.session.commit()
    return product, rep, old, latest, summary


def test_newer_compact_snapshot_overlays_tl_but_preserves_direct_box_authority(tmp_path):
    app = _app(tmp_path)
    with app.app_context():
        product, rep, old, latest, summary = _seed()

        national = OfficialAggregateService.product_totals(2041, 3, "NATIONAL")
        assert len(national) == 1
        row = national[0]
        assert row["product_id"] == product.id
        assert row["target_tl"] == 200.0
        assert row["actual_tl"] == 150.0
        assert row["target_unit"] == 20.0
        assert row["actual_unit"] == 10.0

        region = RegionPerformanceService("901", 2041, 3)._official_ims_region_month(2041, 3)
        assert region[product.id][0] == 200.0
        assert region[product.id][1] == 150.0
        assert region[product.id][2] is True


def test_numeric_zero_in_new_snapshot_replaces_old_official_tl(tmp_path):
    app = _app(tmp_path)
    with app.app_context():
        product, rep, old, latest, summary = _seed()
        summary.tl = 0.0
        db.session.commit()

        national = OfficialAggregateService.product_totals(2041, 3, "NATIONAL")
        assert national[0]["actual_tl"] == 0.0
        assert national[0]["actual_unit"] == 10.0


def test_incomplete_target_scope_does_not_replace_official_target(tmp_path):
    app = _app(tmp_path)
    with app.app_context():
        product, rep, old, latest, summary = _seed()
        extra = Representative(
            rep_code="OVERLAY-EXTRA", rep_name="OVERLAY EXTRA", region="902", active=True
        )
        db.session.add(extra); db.session.flush()
        db.session.add(IMSSummary(
            upload_id=latest.id, year=2041, month=3, quarter="Q1",
            representative_id=extra.id, product_id=product.id,
            target_tl=0.0, target_unit=0.0, tl=25.0, unit=0.0,
        ))
        latest.summary_record_count = 2
        db.session.commit()

        national = OfficialAggregateService.product_totals(2041, 3, "NATIONAL")
        assert national[0]["target_tl"] == 100.0
        assert national[0]["actual_tl"] == 175.0
        assert national[0]["target_unit"] == 20.0


def test_map_region_uses_latest_compact_tl_and_current_target_roster(tmp_path):
    app = _app(tmp_path)
    with app.app_context():
        product, rep, old, latest, summary = _seed()

        rows = DashboardQuery().load_region_performance(
            DashboardFilterParams(year=2041, month=3)
        )
        region = next(row for row in rows if str(row.region) == "901")
        assert region.tl_target == 200.0
        assert region.tl_actual == 150.0
        # Box metrics stay on the prior direct region source.
        assert region.unit_target == 20.0
        assert region.unit_actual == 10.0
        assert region.representative_count == 1


def test_map_region_numeric_zero_is_real_latest_actual(tmp_path):
    app = _app(tmp_path)
    with app.app_context():
        product, rep, old, latest, summary = _seed()
        summary.tl = 0.0
        db.session.commit()

        rows = DashboardQuery().load_region_performance(
            DashboardFilterParams(year=2041, month=3)
        )
        region = next(row for row in rows if str(row.region) == "901")
        assert region.tl_actual == 0.0
        assert region.unit_actual == 10.0
