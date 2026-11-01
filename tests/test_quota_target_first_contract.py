"""Target-first quota contract: explicit production approval and one credit."""
import pytest

from app import create_app
from app.extensions import db
from app.models import (Product, Representative, Target, IMSSummary, ProductionResultUpload,
                        ProductionResult, ProductionRegionProductResult, ProductionNationalProductResult)
from app.services.production_result_service import ProductionResultService as Results
from app.services.quarter_entitlement_service import QuarterEntitlementService


@pytest.fixture
def quota_audit(tmp_path):
    class Config:
        TESTING = True
        SECRET_KEY = "quota-contract-audit"
        SQLALCHEMY_DATABASE_URI = "sqlite://"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        UPLOAD_FOLDER = tmp_path / "uploads"
        REPORT_FOLDER = tmp_path / "reports"
        BACKUP_FOLDER = tmp_path / "backups"
        LOG_FOLDER = tmp_path / "logs"

    app = create_app(Config)
    with app.app_context():
        db.create_all()
        rep = Representative(rep_code="AUDIT", rep_name="Audit representative", region="901", active=True)
        product = Product(product_code="DYNAMIC-A", product_name="Degisen Urun", is_active=True)
        db.session.add_all([rep, product]); db.session.commit()
        yield rep, product
        db.session.remove()


@pytest.mark.parametrize("target", [None, 0, 500])
@pytest.mark.parametrize("production_applied", [False, True])
@pytest.mark.parametrize("meaningful_sale", [False, True])
@pytest.mark.parametrize("filename_marker", [False, True])
def test_quota_requires_target_and_production_auto_or_explicit_confirmation(
    quota_audit, target, production_applied, meaningful_sale, filename_marker,
):
    rep, product = quota_audit
    if target is not None:
        db.session.add(Target(year=2045, month=7, representative_id=rep.id,
                              product_id=product.id, tl_target=target, unit_target=5 if target else 0))
    actual, units = (5000, 50) if meaningful_sale else (0, 0)
    db.session.add(IMSSummary(year=2045, month=7, representative_id=rep.id,
                             product_id=product.id, tl=actual, unit=units))
    upload = ProductionResultUpload(
        file_name="Uretim" + (" KOTA CIKIS Degisen Urun" if filename_marker else "") + ".xlsx",
        stored_file_name="audit.xlsx", source_hash="a" * 64, year=2045, month=7,
        production_stage=2, status="APPLIED" if production_applied else "PENDING_VALIDATION",
    )
    db.session.add(upload); db.session.flush()
    db.session.add_all([
        ProductionResult(upload_id=upload.id, representative_id=rep.id, product_id=product.id,
                         target_tl=target or 0, target_unit=5 if target else 0,
                         actual_tl=actual, actual_unit=units, realization_percent=1000 if meaningful_sale else 0),
        ProductionRegionProductResult(upload_id=upload.id, region_code="901", product_id=product.id,
                                      target_tl=target or 0, target_unit=5 if target else 0,
                                      actual_tl=actual, actual_unit=units,
                                      realization_percent=1000 if meaningful_sale else 0, unit_realization_percent=0),
        ProductionNationalProductResult(upload_id=upload.id, product_id=product.id,
                                        actual_tl=actual, actual_unit=units,
                                        realization_percent=1000 if meaningful_sale else 0, unit_realization_percent=0),
    ])
    db.session.commit()
    # An explicit production quota marker is approval, even with sales.
    expected = {product.id: [(2045, 7)]} if target and production_applied and (filename_marker or not meaningful_sale) else {}
    assert Results.quota_product_months([(2045, 7)]) == expected


@pytest.mark.parametrize("target", [0, 500])
@pytest.mark.parametrize("already_credited", [False, True])
def test_quarter_does_not_credit_targetless_or_already_closed_product_twice(quota_audit, target, already_credited):
    rep, product = quota_audit
    db.session.add(Target(year=2045, month=7, representative_id=rep.id,
                          product_id=product.id, tl_target=target, unit_target=0))
    db.session.commit()
    service = QuarterEntitlementService.__new__(QuarterEntitlementService)
    service.year, service.representative_id = 2045, rep.id
    service._official_quota = {7: [product.id]} if target else {}
    service.quota_exit_by_month, service._snapshot_rows = {}, {}
    service._product_meta = lambda: {product.id: {"product_name": product.product_name}}
    service._snapshot_month = lambda month: {"products": [{
        "product": {"id": product.id, "product_name": product.product_name},
        "target_tl": target if already_credited else 0,
        "actual_tl": target if already_credited else 0, "target_unit": 0, "actual_unit": 0,
    }]}
    first, _, _ = service._snapshot_products(7)
    second, _, _ = service._snapshot_products(7)
    assert first == second
    if not target:
        assert first is None  # no-target product does not enter the calculation
        return
    assert first[0]["target_tl"] == target and first[0]["actual_tl"] == target
    assert first[0]["percent"] == (100 if target else 0)
    assert first[0]["quota_uplift_tl"] == (target if not already_credited else 0)


def test_quarter_manual_selection_cannot_award_before_production_confirmation(quota_audit):
    rep, product = quota_audit
    db.session.add(Target(year=2045, month=7, representative_id=rep.id,
                          product_id=product.id, tl_target=500, unit_target=5))
    db.session.commit()
    assert Results.quota_product_months([(2045, 7)]) == {}
    service = QuarterEntitlementService.__new__(QuarterEntitlementService)
    service.year, service.representative_id = 2045, rep.id
    service._official_quota, service._snapshot_rows = {}, {}
    service.quota_exit_by_month = {7: product.id}
    service._product_meta = lambda: {product.id: {"product_name": product.product_name}}
    service._snapshot_month = lambda month: {"products": [{
        "product": {"id": product.id, "product_name": product.product_name},
        "target_tl": 500, "actual_tl": 0, "target_unit": 5, "actual_unit": 0,
    }]}
    rows, _, _ = service._snapshot_products(7)
    assert rows[0]["actual_tl"] == 0 and rows[0]["quota_uplift_tl"] == 0


def test_omitted_unsold_product_has_same_quota_result_in_representative_consumers(quota_audit):
    from app.services.representative_period_snapshot_service import RepresentativePeriodSnapshotService
    from app.services.representative_period_workspace import _aggregate_sales

    rep, product = quota_audit
    db.session.add_all([
        Target(year=2045, month=7, representative_id=rep.id, product_id=product.id, tl_target=500, unit_target=5),
        IMSSummary(year=2045, month=7, representative_id=rep.id, product_id=product.id, tl=0, unit=0),
    ])
    other = Product(product_code="DYNAMIC-B", product_name="Baska Urun", is_active=True)
    upload = ProductionResultUpload(file_name="Uretim.xlsx", stored_file_name="audit.xlsx",
                                    source_hash="b" * 64, year=2045, month=7, production_stage=2, status="APPLIED")
    db.session.add_all([other, upload]); db.session.flush()
    db.session.add(ProductionNationalProductResult(upload_id=upload.id, product_id=other.id,
                                                  actual_tl=5000, actual_unit=50,
                                                  realization_percent=100, unit_realization_percent=100))
    db.session.commit()
    assert Results.quota_product_months([(2045, 7)]) == {product.id: [(2045, 7)]}
    _, workspace_totals, _, _ = _aggregate_sales(rep.id, [(2045, 7)])
    snapshot = RepresentativePeriodSnapshotService.build(rep.id, 2045, 7)
    assert workspace_totals["actual_tl"] == 500
    assert snapshot["monthly"]["actual_tl"] == workspace_totals["actual_tl"]


@pytest.mark.parametrize('year,month,excluded', [(2026,9,False),(2026,10,True),(2045,7,True)])
def test_targetless_sales_are_excluded_only_from_new_contract(quota_audit,year,month,excluded):
    from app.services.representative_period_workspace import _aggregate_sales
    from app.services.annual_realization_service import AnnualRealizationService
    from app.services.representative_period_snapshot_service import RepresentativePeriodSnapshotService
    rep,product=quota_audit
    db.session.add_all([
        Target(year=year,month=month,representative_id=rep.id,product_id=product.id,tl_target=0,unit_target=0),
        IMSSummary(year=year,month=month,representative_id=rep.id,product_id=product.id,tl=250,unit=10),
    ])
    db.session.commit()
    effective=Results.effective_product(year,month,rep.id,product.id)
    assert bool(effective.get('out_of_scope')) is excluded
    assert effective['actual_tl'] == (0 if excluded else 250)
    _,totals,_,_=_aggregate_sales(rep.id,[(year,month)])
    assert totals['actual_tl'] == (0 if excluded else 250)
    chart=AnnualRealizationService.build_representative(year,rep.id)
    assert chart[month-1]['actual_tl'] == (0 if excluded else 250)
    snapshot=RepresentativePeriodSnapshotService.build(rep.id,year,month)
    assert (snapshot['monthly']['actual_tl'] or 0) == (0 if excluded else 250)
    assert bool(snapshot['monthly']['products']) is not excluded
    service=QuarterEntitlementService.__new__(QuarterEntitlementService)
    service.year,service.representative_id=year,rep.id
    service._product_meta=lambda:{product.id:{'product_name':product.product_name}}
    assert bool(service._historical_products(month)) is not excluded


def test_region_quota_closes_own_official_target_not_shared_brick_rep_total(quota_audit):
    from app.models import IMSUpload,IMSRawData
    from app.services.region_performance_service import RegionPerformanceService
    rep,product=quota_audit
    ims=IMSUpload(file_name='ims.xlsx',year=2045,month=7,status='COMPLETED')
    upload=ProductionResultUpload(file_name='Uretim KOTA CIKIS Degisen Urun.xlsx',stored_file_name='p.xlsx',
        source_hash='d'*64,year=2045,month=7,production_stage=2,status='APPLIED')
    db.session.add_all([ims,upload]);db.session.flush()
    db.session.add_all([
        Target(year=2045,month=7,representative_id=rep.id,product_id=product.id,tl_target=900,unit_target=90),
        IMSRawData(upload_id=ims.id,year=2045,month=7,sheet_name='KPI',sheet_type='official_target_aggregate',territory='901',product_id=product.id,tl=500,unit=50,raw_json='{}'),
        ProductionRegionProductResult(upload_id=upload.id,region_code='901',product_id=product.id,
            target_tl=0,target_unit=0,actual_tl=250,actual_unit=25,realization_percent=50,unit_realization_percent=50),
    ])
    db.session.commit()
    values=RegionPerformanceService('901',2045,7)._official_ims_region_month(2045,7)[product.id]
    assert values[:2] == [500,500]


def test_quota_product_is_dynamic_and_can_change_between_months(quota_audit):
    rep, first = quota_audit
    second = Product(product_code="DYNAMIC-SECOND", product_name="Baska Degisen Urun", is_active=True)
    db.session.add(second); db.session.flush()
    for month, active in ((7, first), (8, second)):
        upload = ProductionResultUpload(file_name=f"Uretim-{month}.xlsx", stored_file_name=f"audit-{month}.xlsx",
                                        source_hash=str(month) * 64, year=2045, month=month,
                                        production_stage=2, status="APPLIED")
        db.session.add(upload); db.session.flush()
        for product in (first, second):
            db.session.add_all([
                Target(year=2045, month=month, representative_id=rep.id, product_id=product.id,
                       tl_target=500 if product is active else 0, unit_target=5 if product is active else 0),
                ProductionResult(upload_id=upload.id, representative_id=rep.id, product_id=product.id,
                                 target_tl=0, target_unit=0, actual_tl=0, actual_unit=0, realization_percent=0),
                ProductionNationalProductResult(upload_id=upload.id, product_id=product.id,
                                                actual_tl=0, actual_unit=0, realization_percent=0, unit_realization_percent=0),
            ])
    db.session.commit()
    assert Results.quota_product_months([(2045, 7), (2045, 8)]) == {
        first.id: [(2045, 7)], second.id: [(2045, 8)],
    }


@pytest.mark.parametrize("already_closed_in_production", [False, True])
def test_explicit_quota_approval_accepts_partial_sales_without_requiring_preclosed_percent(
    quota_audit, already_closed_in_production,
):
    rep, product = quota_audit
    db.session.add_all([
        Target(year=2045, month=7, representative_id=rep.id, product_id=product.id, tl_target=500, unit_target=20),
        IMSSummary(year=2045, month=7, representative_id=rep.id, product_id=product.id, tl=250, unit=10),
    ])
    upload = ProductionResultUpload(file_name="Uretim KOTA CIKIS Degisen Urun.xlsx", stored_file_name="partial.xlsx",
                                    source_hash="c" * 64, year=2045, month=7, production_stage=2, status="APPLIED")
    db.session.add(upload); db.session.flush()
    actual = 500 if already_closed_in_production else 250
    percent = 100 if already_closed_in_production else 50
    db.session.add_all([
        ProductionResult(upload_id=upload.id, representative_id=rep.id, product_id=product.id,
                         target_tl=500, target_unit=20, actual_tl=actual, actual_unit=10, realization_percent=percent),
        ProductionRegionProductResult(upload_id=upload.id, region_code="901", product_id=product.id,
                                      target_tl=500, target_unit=20, actual_tl=actual, actual_unit=10,
                                      realization_percent=percent, unit_realization_percent=50),
        ProductionNationalProductResult(upload_id=upload.id, product_id=product.id,
                                        actual_tl=actual, actual_unit=10,
                                        realization_percent=percent, unit_realization_percent=50),
    ])
    db.session.commit()
    assert Results.quota_product_months([(2045, 7)]) == {product.id: [(2045, 7)]}
    batch = Results.effective_products(2045, 7, rep.id)[product.id]
    single = Results.effective_product(2045, 7, rep.id, product.id)
    assert batch == single
    assert single['target_tl'] == single['actual_tl'] == 500
    assert single['realization_percent'] == 100
    assert single['actual_unit'] == 10  # factual units never become synthetic quota sales
