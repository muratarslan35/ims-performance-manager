from pathlib import Path
import tempfile

from app import create_app
from app.extensions import db
from app.models import IMSSummary, IMSUpload, Product, Representative, Target
from app.services.product_unit_price_service import ProductUnitPriceService, product_unit_price_history
from app.services.production_result_service import ProductionResultService


class Config:
    TESTING = True
    SECRET_KEY = "period-price-history"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = Path(tempfile.gettempdir()) / "period-price-uploads"
    REPORT_FOLDER = Path(tempfile.gettempdir()) / "period-price-reports"
    BACKUP_FOLDER = Path(tempfile.gettempdir()) / "period-price-backups"
    LOG_FOLDER = Path(tempfile.gettempdir()) / "period-price-logs"


def _app():
    app = create_app(Config)
    with app.app_context():
        db.create_all()
    return app


def test_price_edit_becomes_effective_next_month_and_preserves_history(monkeypatch):
    app = _app()
    with app.app_context():
        product = Product(product_code="PRICE", product_name="Price", unit_price=100, is_active=True)
        db.session.add(product)
        db.session.commit()

        monkeypatch.setattr(ProductUnitPriceService, "next_effective_period", classmethod(lambda cls: (2026, 5)))
        ProductUnitPriceService.schedule_price_change(product.id, 100, 125)
        product.unit_price = 125
        db.session.commit()

        assert ProductUnitPriceService.price_for_period(product.id, 2026, 4) == 100
        assert ProductUnitPriceService.price_for_period(product.id, 2026, 5) == 125
        assert ProductUnitPriceService.price_for_period(product.id, 2026, 6) == 125

        # Another edit during May affects June only. May remains frozen at 125.
        monkeypatch.setattr(ProductUnitPriceService, "next_effective_period", classmethod(lambda cls: (2026, 6)))
        ProductUnitPriceService.schedule_price_change(product.id, 125, 150)
        product.unit_price = 150
        db.session.commit()

        assert ProductUnitPriceService.price_for_period(product.id, 2026, 4) == 100
        assert ProductUnitPriceService.price_for_period(product.id, 2026, 5) == 125
        assert ProductUnitPriceService.price_for_period(product.id, 2026, 6) == 150


def test_repeated_midmonth_edit_updates_only_next_month(monkeypatch):
    app = _app()
    with app.app_context():
        product = Product(product_code="PRICE2", product_name="Price2", unit_price=100, is_active=True)
        db.session.add(product)
        db.session.commit()
        monkeypatch.setattr(ProductUnitPriceService, "next_effective_period", classmethod(lambda cls: (2026, 10)))

        ProductUnitPriceService.schedule_price_change(product.id, 100, 120)
        product.unit_price = 120
        ProductUnitPriceService.schedule_price_change(product.id, 120, 130)
        product.unit_price = 130
        db.session.commit()

        rows = db.session.execute(
            product_unit_price_history.select().where(product_unit_price_history.c.product_id == product.id)
        ).all()
        assert len(rows) == 2  # April baseline + one October row
        assert ProductUnitPriceService.price_for_period(product.id, 2026, 9) == 100
        assert ProductUnitPriceService.price_for_period(product.id, 2026, 10) == 130


def test_ims_tl_box_reads_use_period_price_not_latest_master(monkeypatch):
    app = _app()
    with app.app_context():
        product = Product(product_code="BOXPRICE", product_name="BoxPrice", unit_price=100, is_active=True)
        representative = Representative(rep_code="PRICE-REP", rep_name="Price Rep", active=True)
        db.session.add_all([product, representative])
        db.session.flush()

        for month in (4, 5, 6):
            upload = IMSUpload(file_name=f"w-{month}.xlsx", year=2026, month=month, status="COMPLETED")
            db.session.add(upload)
            db.session.flush()
            db.session.add(
                Target(year=2026, month=month, representative_id=representative.id, product_id=product.id, tl_target=1000, unit_target=999)
            )
            db.session.add(
                IMSSummary(upload_id=upload.id, year=2026, month=month, representative_id=representative.id, product_id=product.id, tl=500, unit=999)
            )
        db.session.commit()

        monkeypatch.setattr(ProductUnitPriceService, "next_effective_period", classmethod(lambda cls: (2026, 5)))
        ProductUnitPriceService.schedule_price_change(product.id, 100, 125)
        product.unit_price = 125
        monkeypatch.setattr(ProductUnitPriceService, "next_effective_period", classmethod(lambda cls: (2026, 6)))
        ProductUnitPriceService.schedule_price_change(product.id, 125, 150)
        product.unit_price = 150
        db.session.commit()

        april = ProductionResultService.effective_product(2026, 4, representative.id, product.id)
        may = ProductionResultService.effective_product(2026, 5, representative.id, product.id)
        june = ProductionResultService.effective_product(2026, 6, representative.id, product.id)

        assert (april["target_unit"], april["actual_unit"]) == (10, 5)
        assert (may["target_unit"], may["actual_unit"]) == (8, 4)
        assert (june["target_unit"], june["actual_unit"]) == (7, 3)
