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
            file_name="Mart_2_Uretim.xlsx", stored_file_name="2044-03-p2.xlsx",
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
            travazol_percent = 100 if region_code == "901" else 80
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


def test_region_template_renders_compact_quota_exit_badge():
    template = Path("app/templates/region_performance.html").read_text(encoding="utf-8")
    assert "quota-exit-badge" in template
    assert "Kota Çıkış" in template
    assert "item.quota_exit_months" in template
