from pathlib import Path

from app.extensions import db
from app import create_app
from app.models import (
    Product,
    ProductionRegionProductResult,
    ProductionResultUpload,
    Representative,
    Target,
)


def _app(tmp_path):
    class Config:
        TESTING = True
        SECRET_KEY = "quota-exit"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'quota-exit.db'}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        LOGIN_DISABLED = True
        UPLOAD_FOLDER = tmp_path / "uploads"
        REPORT_FOLDER = tmp_path / "reports"
        BACKUP_FOLDER = tmp_path / "backups"
        LOG_FOLDER = tmp_path / "logs"
        TEMP_FOLDER = tmp_path / "temp"
    return create_app(Config)


def test_region_marks_only_all_region_hundred_percent_product_as_quota_exit(tmp_path):
    from app.services.region_performance_service import RegionPerformanceService

    app = _app(tmp_path)
    with app.app_context():
        db.create_all()
        representative = Representative(
            rep_code="QUOTA-REP", rep_name="KOTA TEMSILCI", region="901", active=True
        )
        monurol = Product(product_code="Q-MON", product_name="Monurol", is_active=True)
        travazol = Product(product_code="Q-TRA", product_name="Travazol", is_active=True)
        db.session.add_all([representative, monurol, travazol])
        db.session.flush()
        for product in (monurol, travazol):
            db.session.add(Target(
                year=2044, month=3, quarter="Q1", representative_id=representative.id,
                product_id=product.id, tl_target=1000, unit_target=10,
            ))
        upload = ProductionResultUpload(
            file_name="Mart_2_Uretim_KOTA_SATIS_Monurol-Fentivag.xlsx",
            stored_file_name="2044-03-p2.xlsx",
            source_hash="q" * 64, year=2044, month=3, production_stage=2,
            status=ProductionResultUpload.STATUS_APPLIED,
        )
        db.session.add(upload)
        db.session.flush()
        for region_code in ("901", "801"):
            monurol_percent = 100 if region_code == "901" else 120
            db.session.add(ProductionRegionProductResult(
                upload_id=upload.id, region_code=region_code, product_id=monurol.id,
                target_tl=1000, actual_tl=1000 * monurol_percent / 100,
                target_unit=10, actual_unit=5, realization_percent=monurol_percent,
                unit_realization_percent=50,
            ))
            # Natural all-region overperformance is not quota unless the
            # product is explicitly named by the workbook quota marker.
            travazol_percent = 120
            db.session.add(ProductionRegionProductResult(
                upload_id=upload.id, region_code=region_code, product_id=travazol.id,
                target_tl=1000, actual_tl=1000 * travazol_percent / 100,
                target_unit=10, actual_unit=8, realization_percent=travazol_percent,
                unit_realization_percent=80,
            ))
        db.session.commit()

        rows = {
            row["product_name"]: row
            for row in RegionPerformanceService("901", 2044, 3).aggregate([(2044, 3)])["products"]
        }
        assert rows[monurol.product_name]["quota_exit"] is True
        assert rows[monurol.product_name]["quota_exit_months"] == ["03/2044"]
        assert rows[travazol.product_name]["quota_exit"] is False
        assert rows[travazol.product_name]["quota_exit_months"] == []



def test_region_market_official_products_returns_authoritative_rows(tmp_path):
    from app.services.region_market_service import RegionMarketService

    app = _app(tmp_path)
    with app.app_context():
        db.create_all()
        representative = Representative(
            rep_code="OFFICIAL-REP", rep_name="OFFICIAL REP", region="901", active=True
        )
        product = Product(
            product_code="OFFICIAL-PROD", product_name="Monurol", is_active=True
        )
        db.session.add_all([representative, product])
        db.session.flush()
        upload = ProductionResultUpload(
            file_name="Temmuz_2_Uretim.xlsx",
            stored_file_name="2044-07-p2.xlsx",
            source_hash="o" * 64,
            year=2044,
            month=7,
            production_stage=2,
            status=ProductionResultUpload.STATUS_APPLIED,
        )
        db.session.add(upload)
        db.session.flush()
        row = ProductionRegionProductResult(
            upload_id=upload.id,
            region_code="901",
            product_id=product.id,
            target_tl=1000,
            actual_tl=800,
            target_unit=10,
            actual_unit=8,
            realization_percent=80,
            unit_realization_percent=80,
        )
        db.session.add(row)
        db.session.commit()

        service = RegionMarketService("901", [representative.id], 2044, 7)
        official = service._official_products(upload.id)

        assert isinstance(official, dict)
        assert official[product.id].id == row.id


def test_region_template_renders_compact_quota_exit_badge():
    template = Path("app/templates/region_performance.html").read_text(encoding="utf-8")
    assert "quota-exit-badge" in template
    assert "Kota Çıkış" in template
    assert "item.quota_exit_months" in template


def test_july_empty_national_product_is_quota_exit_for_every_representative(tmp_path):
    from types import SimpleNamespace
    from app.models import IMSSummary, ProductionNationalProductResult, ProductionResult
    from app.services.production_result_service import ProductionResultService
    from app.services.quarter_entitlement_service import QuarterEntitlementService

    app = _app(tmp_path)
    with app.app_context():
        db.create_all()
        reps = [
            Representative(rep_code=f"JULY-{index}", rep_name=f"July Rep {index}",
                           region=str(900 + index), active=True)
            for index in (1, 2)
        ]
        fentivag = Product(product_code="JULY-FEN", product_name="Fentivag", is_active=True)
        db.session.add_all([*reps, fentivag])
        db.session.flush()
        upload = ProductionResultUpload(
            file_name="Temmuz_2_Uretim.xlsx", stored_file_name="2044-07-p2.xlsx",
            source_hash="j" * 64, year=2044, month=7, production_stage=2,
            status=ProductionResultUpload.STATUS_APPLIED,
        )
        db.session.add(upload)
        db.session.flush()
        for rep in reps:
            db.session.add_all([
                Target(year=2044, month=7, representative_id=rep.id,
                       product_id=fentivag.id, tl_target=500, unit_target=5),
                IMSSummary(year=2044, month=7, representative_id=rep.id,
                           product_id=fentivag.id, tl=0, unit=0),
                ProductionResult(upload_id=upload.id, representative_id=rep.id,
                                 product_id=fentivag.id, target_tl=0, target_unit=0,
                                 actual_tl=0, actual_unit=0, realization_percent=0),
            ])
        for rep in reps:
            db.session.add(ProductionRegionProductResult(
                upload_id=upload.id, region_code=rep.region,
                product_id=fentivag.id, target_tl=0, actual_tl=0,
                target_unit=0, actual_unit=0,
                realization_percent=0, unit_realization_percent=0,
            ))
        db.session.add(ProductionNationalProductResult(
            upload_id=upload.id, product_id=fentivag.id, actual_tl=0,
            actual_unit=0, realization_percent=0, unit_realization_percent=0,
        ))
        db.session.commit()

        assert ProductionResultService.quota_product_months([(2044, 7)]) == {
            fentivag.id: [(2044, 7)]
        }
        from app.services.region_performance_service import RegionPerformanceService
        from app.services.representative_period_snapshot_service import RepresentativePeriodSnapshotService
        from app.services.annual_realization_service import AnnualRealizationService
        region = RegionPerformanceService(reps[0].region, 2044, 7).report()
        region_monthly = region["periods"]["monthly"]
        assert region_monthly["target_tl"] == 500
        assert region_monthly["actual_tl"] == 500
        assert region_monthly["realization_percent"] == 100
        assert region["annual_realization"][6]["percent"] == 100
        for rep in reps:
            snapshot = RepresentativePeriodSnapshotService.build(rep.id, 2044, 7)
            assert snapshot["monthly"]["actual_tl"] == 500
            assert snapshot["monthly"]["realization_percent"] == 100
            assert AnnualRealizationService.build_representative(2044, rep.id)[6]["percent"] == 100
            service = QuarterEntitlementService.__new__(QuarterEntitlementService)
            service.year, service.representative_id = 2044, rep.id
            service._official_quota = {7: [fentivag.id]}
            service.quota_exit_by_month = {}
            service._snapshot_rows = {}
            service.engine = SimpleNamespace(
                products=[fentivag], get_prime_rule=lambda _product: None,
            )
            service._snapshot_month = lambda _month: {
                "months": [[2044, 7]], "products": [{
                    "product": {"id": fentivag.id, "product_name": "Fentivag"},
                    "target_tl": 0, "actual_tl": 0,
                    "target_unit": 0, "actual_unit": 0,
                }],
            }
            products, quota, available = service._snapshot_products(7)
            assert available and quota["auto_selected"] is True
            assert products[0]["target_tl"] == 500
            assert products[0]["actual_tl"] == 500
            assert products[0]["quota_uplift_tl"] == 500

        # Finalized production supersedes earlier IMS sales.
        db.session.query(IMSSummary).filter_by(representative_id=reps[1].id).update({"tl": 1})
        db.session.commit()
        assert ProductionResultService.quota_product_months([(2044, 7)]) == {
            fentivag.id: [(2044, 7)]
        }
        db.session.query(ProductionResult).filter_by(representative_id=reps[1].id).update({"actual_tl": 1})
        db.session.commit()
        assert ProductionResultService.quota_product_months([(2044, 7)]) == {}

        # A product omitted entirely from the final production workbook is
        # still a quota exit when nationwide IMS sales are zero.
        db.session.query(IMSSummary).update({"tl": 0})
        db.session.query(ProductionResult).delete()
        db.session.query(ProductionNationalProductResult).delete()
        db.session.query(ProductionRegionProductResult).delete()
        db.session.commit()
        another_product = Product(product_code="JULY-OTHER", product_name="Another product", is_active=True)
        db.session.add(another_product)
        db.session.flush()
        db.session.add(ProductionNationalProductResult(
            upload_id=upload.id, product_id=another_product.id, actual_tl=10,
            actual_unit=1, realization_percent=100, unit_realization_percent=100,
        ))
        db.session.commit()
        db.session.query(IMSSummary).filter_by(representative_id=reps[1].id).update({"tl": 1})
        db.session.commit()
        assert ProductionResultService.quota_product_months([(2044, 7)]) == {}
        db.session.query(IMSSummary).filter_by(representative_id=reps[1].id).update({"tl": 0})
        db.session.commit()
        assert ProductionResultService.quota_product_months([(2044, 7)]) == {
            fentivag.id: [(2044, 7)]
        }
        db.session.add(ProductionNationalProductResult(
            upload_id=upload.id, product_id=fentivag.id, actual_tl=1,
            actual_unit=0, realization_percent=0, unit_realization_percent=0,
        ))
        db.session.commit()
        assert ProductionResultService.quota_product_months([(2044, 7)]) == {}
