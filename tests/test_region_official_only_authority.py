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
        for month, week in ((8,35),(9,40),(10,41)):
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
    september = service.aggregate([(2026,9)])["products"][0]
    assert (september["target_unit"],september["actual_unit"]) == (Decimal(100),Decimal(50))
    assert (combined["target_unit"],combined["actual_unit"]) == (Decimal(200),Decimal(100))
    legacy = service.aggregate([(2026,8)])["products"][0]
    assert (legacy["target_unit"],legacy["actual_unit"]) == (Decimal(200),Decimal(120))
    across_boundary = service.aggregate([(2026,8),(2026,9)])["products"][0]
    assert (across_boundary["target_unit"],across_boundary["actual_unit"]) == (Decimal(300),Decimal(170))


@pytest.mark.parametrize('month',[9,10])
def test_missing_official_region_fails_instead_of_using_shared_bricks(region,month):
    service, _ = region
    IMSRawData.query.delete(); db.session.commit()
    with pytest.raises(ValueError,match="Official region subtotal missing"):
        service.aggregate([(2026,month)])
    october = service._annual_region_realization()[month-1]
    assert october["has_data"] is False
    assert october["source"] == "MISSING_OFFICIAL_REGION_SUBTOTAL"


@pytest.mark.parametrize('month',[9,10])
def test_real_zero_region_total_remains_zero_despite_positive_representatives(region,month):
    service, _ = region
    IMSRawData.query.update({IMSRawData.tl:0}); db.session.commit()
    row = service.aggregate([(2026,month)])["products"][0]
    assert (row["target_tl"],row["actual_tl"],row["target_unit"],row["actual_unit"]) == (0,0,0,0)


def test_pre_september_period_retains_accepted_legacy_fallback(region):
    service, _ = region
    IMSRawData.query.filter_by(year=2026,month=8).delete(); db.session.commit()
    row=service.aggregate([(2026,8)])["products"][0]
    assert (row["target_tl"],row["actual_tl"],row["target_unit"],row["actual_unit"]) == (2000,1200,200,120)
    assert service._uses_official_region_only(2026,8) is False
    assert service._uses_official_region_only(2026,9) is True
    assert service._uses_official_region_only(2026,10) is True


def test_september_dashboard_map_uses_official_product_tl_and_period_price(region):
    service, _ = region
    from app.query.dashboard_query import DashboardQuery
    from app.query.filters import DashboardFilterParams
    rows=DashboardQuery().load_region_performance(DashboardFilterParams(year=2026,month=9))
    row=next(item for item in rows if str(item.region)=='901')
    assert (row.tl_target,row.tl_actual)==(1000,500)
    assert (row.unit_target,row.unit_actual)==(100,50)


def test_september_roster_uses_source_identities_without_deleting_old_targets(region):
    service,pid=region
    upload=IMSUpload.query.filter_by(year=2026,month=9).one()
    source_reps=set(service.rep_ids)
    for rid in source_reps:
        db.session.add(IMSRawData(upload_id=upload.id,year=2026,month=9,
            sheet_name='legacy TTS',sheet_type='brick_sales',territory='901',
            representative_id=rid,product_id=pid,tl=600,unit=60,raw_json='{}'))
    old=Representative(rep_code='OLD',rep_name='Obsolete vacancy',region='901',active=False)
    db.session.add(old);db.session.flush()
    db.session.add(Target(year=2026,month=9,representative_id=old.id,product_id=pid,tl_target=500,unit_target=50))
    db.session.commit()
    rebuilt=RegionPerformanceService('901',2026,9).aggregate([(2026,9)])
    assert {r['representative_id'] for r in rebuilt['representatives']}==source_reps
    assert {r['representative_id'] for r in rebuilt['representative_products']}==source_reps
    assert Target.query.filter_by(year=2026,month=9,representative_id=old.id).count()==1


@pytest.mark.parametrize('month',[9,10])
def test_market_effective_company_matches_region_without_changing_market_denominator(region,month):
    service, pid = region
    service.month=month
    from app.services.region_box_authority_guard import _apply_official_region_market_boxes
    payload = {"rows":[{"product_id":pid,"target_unit":200,"company_unit":120,
        "market_company_unit":999,"market_unit":1100,"competitor_unit":101,
        "share_percent":91}],"totals":{"company_unit":999,"market_unit":1100}}
    result=_apply_official_region_market_boxes(service,payload)
    row=result["rows"][0]
    assert (row["target_unit"],row["company_unit"],row["realization_percent"]) == (100,50,50)
    assert (row["market_company_unit"],row["market_unit"],row["competitor_unit"],row["share_percent"]) == (999,1100,101,91)
    assert result["totals"]["effective_company_unit"] == 50
    assert result["totals"]["company_unit"] == 999
    service.month=8
    legacy={"rows":[{"product_id":pid,"target_unit":200,"company_unit":120}]}
    assert _apply_official_region_market_boxes(service,legacy)==legacy
