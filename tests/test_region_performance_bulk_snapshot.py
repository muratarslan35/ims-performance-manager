from pathlib import Path

from sqlalchemy import event

from app import create_app
from app.extensions import db
from app.models import IMSSummary, Product, Representative, Target
from app.services.region_performance_service import RegionPerformanceService


class RegionBulkConfig:
    TESTING = True
    SECRET_KEY = "region-bulk-snapshot"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    UPLOAD_FOLDER = Path("/tmp/region-bulk-snapshot/uploads")
    REPORT_FOLDER = Path("/tmp/region-bulk-snapshot/reports")
    BACKUP_FOLDER = Path("/tmp/region-bulk-snapshot/backups")
    LOG_FOLDER = Path("/tmp/region-bulk-snapshot/logs")
    TEMP_FOLDER = Path("/tmp/region-bulk-snapshot/temp")


def _seed_region():
    products = [
        Product(product_code=f"BULK{idx}", product_name=f"Bulk Product {idx}", display_order=idx)
        for idx in range(1, 8)
    ]
    representatives = [
        Representative(
            rep_code=f"BULKREP{idx}",
            rep_name=f"Bulk Representative {idx}",
            region="901",
            city="DIYARBAKIR",
            active=True,
        )
        for idx in range(1, 11)
    ]
    db.session.add_all(products + representatives)
    db.session.flush()

    for month in (1, 2, 3):
        for representative in representatives:
            for product in products:
                db.session.add(Target(
                    year=2026,
                    month=month,
                    representative_id=representative.id,
                    product_id=product.id,
                    tl_target=100.0,
                    unit_target=10.0,
                ))
                db.session.add(IMSSummary(
                    year=2026,
                    month=month,
                    representative_id=representative.id,
                    product_id=product.id,
                    tl=50.0,
                    unit=5.0,
                    target_tl=100.0,
                    target_unit=10.0,
                ))
    db.session.commit()


def test_region_report_uses_one_bounded_source_snapshot_for_overlapping_periods():
    app = create_app(RegionBulkConfig)
    with app.app_context():
        db.create_all()
        _seed_region()
        service = RegionPerformanceService("901", 2026, 3)

        selects = []

        def count_selects(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        event.listen(db.engine, "before_cursor_execute", count_selects)
        try:
            report = service.report()
        finally:
            event.remove(db.engine, "before_cursor_execute", count_selects)

        monthly = report["periods"]["monthly"]
        assert float(monthly["target_tl"]) == 7000.0
        assert float(monthly["actual_tl"]) == 3500.0
        assert float(monthly["realization_percent"]) == 50.0
        assert len(monthly["representatives"]) == 10
        assert len(monthly["products"]) == 7

        # Before the optimizer, effective_product/final_product_result fan-out
        # makes this fixture generate hundreds/thousands of SELECTs. Keep the
        # region page bounded even as representative/product row count grows.
        assert len(selects) <= 120

        source_selects = "\n".join(selects).lower()
        assert source_selects.count("from targets") < 25
        assert source_selects.count("from ims_summary") < 10
        assert source_selects.count("from production_results") <= 1
