from pathlib import Path

path = Path('tests/test_region_read_v2.py')
source = path.read_text()
old = '''def test_region_product_unit_gap_uses_official_stored_units(tmp_path):
    app = _app(tmp_path)
    from app.extensions import db
    from app.models import IMSRawData, IMSUpload, Product, Representative, Target
    from app.services.official_aggregate_service import TARGET_TYPE, ACTUAL_TYPE
    from app.services.region_performance_service import RegionPerformanceService

    with app.app_context():
        db.create_all()
        product = Product(product_code="UNITGAP", product_name="Unit Gap", is_active=True)
        rep = Representative(rep_code="UNITR", rep_name="Unit Rep", region="901", city="Diyarbakır", active=True)
        db.session.add_all([product, rep]); db.session.flush()
        upload = IMSUpload(file_name="units.xlsx", year=2026, month=2, week_number=9, status="COMPLETED", completed_at=datetime(2026, 2, 28))
        db.session.add(upload); db.session.flush()
        db.session.add(Target(year=2026, month=2, representative_id=rep.id, product_id=product.id, tl_target=1000, unit_target=100))
        db.session.add_all([
            IMSRawData(upload_id=upload.id, year=2026, month=2, sheet_name="BAKIYE", sheet_type=TARGET_TYPE, source_row=0, product_id=product.id, territory="901", unit=100, tl=1000, raw_json="{}"),
            IMSRawData(upload_id=upload.id, year=2026, month=2, sheet_name="CIKIS", sheet_type=ACTUAL_TYPE, source_row=0, product_id=product.id, territory="901", unit=112, tl=1100, raw_json="{}"),
        ])
        db.session.commit()
        row = RegionPerformanceService("901", 2026, 2).report()["periods"]["monthly"]["products"][0]
        assert row["target_unit"] == Decimal("100.0")
        assert row["actual_unit"] == Decimal("112.0")
        assert row["unit_difference"] == Decimal("12.0")
'''
new = '''def test_region_product_unit_gap_uses_mf_siz_kutu_balance_not_actual_aggregate(tmp_path):
    app = _app(tmp_path)
    from app.extensions import db
    from app.models import IMSRawData, IMSUpload, Product, Representative, Target
    from app.services.official_aggregate_service import TARGET_TYPE, ACTUAL_TYPE
    from app.services.region_performance_service import RegionPerformanceService

    with app.app_context():
        db.create_all()
        product = Product(product_code="UNITGAP", product_name="Unit Gap", is_active=True)
        rep = Representative(rep_code="UNITR", rep_name="Unit Rep", region="901", city="Diyarbakır", active=True)
        db.session.add_all([product, rep]); db.session.flush()
        upload = IMSUpload(file_name="units.xlsx", year=2026, month=2, week_number=9, status="COMPLETED", completed_at=datetime(2026, 2, 28))
        db.session.add(upload); db.session.flush()
        db.session.add(Target(year=2026, month=2, representative_id=rep.id, product_id=product.id, tl_target=1000, unit_target=100))
        db.session.add_all([
            IMSRawData(upload_id=upload.id, year=2026, month=2, sheet_name="BAKIYE", sheet_type=TARGET_TYPE, source_row=0, product_id=product.id, territory="901", unit=100, tl=1000, raw_json="{}"),
            IMSRawData(upload_id=upload.id, year=2026, month=2, sheet_name="CIKIS", sheet_type=ACTUAL_TYPE, source_row=0, product_id=product.id, territory="901", unit=112, tl=1100, raw_json="{}"),
            IMSRawData(upload_id=upload.id, year=2026, month=2, sheet_name="BAKIYE", sheet_type="dashboard_balance_region", source_row=0, product_id=product.id, territory="901", unit=12, tl=100, raw_json="{}"),
        ])
        db.session.commit()
        row = RegionPerformanceService("901", 2026, 2).report()["periods"]["monthly"]["products"][0]
        assert row["target_unit"] == Decimal("100.0")
        assert row["actual_unit"] == Decimal("88.0")
        assert row["unit_difference"] == Decimal("-12.0")
'''
if old not in source:
    raise SystemExit('target test block not found')
path.write_text(source.replace(old, new, 1))
