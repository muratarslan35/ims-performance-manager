from decimal import Decimal
from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.models import IMSRawData, IMSSummary, IMSUpload, Product, Representative, Target
from app.services.region_performance_service import RegionPerformanceService


@pytest.fixture
def region(tmp_path):
    class Config:
        TESTING = True
        SECRET_KEY = "official-only-test"
        SQLALCHEMY_DATABASE_URI = "sqlite://"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        UPLOAD_FOLDER = tmp_path / "uploads"
        REPORT_FOLDER = tmp_path / "reports"
        BACKUP_FOLDER = tmp_path / "backups"
        LOG_FOLDER = tmp_path / "logs"
    app = create_app(Config)
    with app.app_context():
        db.create_all()
        product = Product(product_code="REGION", product_name="Region product", unit_price=10)
        reps = [Representative(rep_code=f"R{i}", rep_name=f"Shared Brick Rep {i}", region="901") for i in range(2)]
        db.session.add_all([product, *reps]); db.session.flush()
        for month, week in ((9,40),(10,41)):
            upload = IMSUpload(file_name=f"week{week}.xlsx",year=2026,month=month,week_number=week,status="COMPLETED")
            db.session.add(upload); db.session.flush()
            for kind, value in (("official_target_aggregate",1000),("official_actual_aggregate",500)):
                db.session.add(IMSRawData(upload_id=upload.id,year=2026,month=month,
                    sheet_name="official region",sheet_type=kind,territory="901",
                    product_id=product.id,tl=value,unit=99999,raw_json="{}"))
            for rep in reps:
                db.session.add(Target(year=2026,month=month,representative_id=rep.id,
                    product_id=product.id,tl_target=1000,unit_target=9000))
                db.session.add(IMSSummary(upload_id=upload.id,year=2026,month=month,
                    representative_id=rep.id,product_id=product.id,tl=600,unit=9000))
        db.session.commit()
        yield RegionPerformanceService("901",2026,10), product.id
        db.session.remove(); db.drop_all()


def test_shared_brick_representative_sums_never_replace_region_values(region):
    service, _ = region
    monthly = service.aggregate([(2026,10)])
    row = monthly["products"][0]
    assert (row["target_tl"],row["actual_tl"]) == (Decimal(1000),Decimal(500))
    assert (row["target_unit"],row["actual_unit"],row["unit_difference"]) == (Decimal(100),Decimal(50),Decimal(-50))
    assert sum(r["target_tl"] for r in monthly["representatives"]) == 2000
    assert sum(r["actual_tl"] for r in monthly["representatives"]) == 1200
    combined = service.aggregate([(2026,9),(2026,10)])["products"][0]
    assert (combined["target_unit"],combined["actual_unit"]) == (Decimal(200),Decimal(100))


def test_missing_official_region_fails_instead_of_using_shared_bricks(region):
    service, _ = region
    IMSRawData.query.delete(); db.session.commit()
    with pytest.raises(ValueError,match="Official region subtotal missing"):
        service.aggregate([(2026,10)])
    october = service._annual_region_realization()[9]
    assert october["has_data"] is False
    assert october["source"] == "MISSING_OFFICIAL_REGION_SUBTOTAL"


def test_real_zero_region_total_remains_zero_despite_positive_representatives(region):
    service, _ = region
    IMSRawData.query.update({IMSRawData.tl:0}); db.session.commit()
    row = service.aggregate([(2026,10)])["products"][0]
    assert (row["target_tl"],row["actual_tl"],row["target_unit"],row["actual_unit"]) == (0,0,0,0)
