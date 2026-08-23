import tempfile
from pathlib import Path

from flask_migrate import upgrade

from app import create_app
from app.extensions import db
from app.models import CompetitionData, IMSUpload, Product, Representative, Target
from app.services.region_market_service import RegionMarketService


def test_region_market_analysis_aggregates_region_once_and_excludes_other_regions():
    temporary = tempfile.TemporaryDirectory()
    database_path = Path(temporary.name) / "region-market.db"

    class Config:
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        UPLOAD_FOLDER = Path(temporary.name) / "uploads"
        REPORT_FOLDER = Path(temporary.name) / "reports"
        BACKUP_FOLDER = Path(temporary.name) / "backups"
        LOG_FOLDER = Path(temporary.name) / "logs"

    application = create_app(Config)
    try:
        with application.app_context():
            upgrade(directory=str(Path(__file__).resolve().parents[1] / "migrations"))
            product = Product(product_code="TRAVAZOL", product_name="Travazol", display_order=1, is_active=True)
            first = Representative(rep_code="R1", rep_name="Temsilci Bir", region="901", active=True)
            second = Representative(rep_code="R2", rep_name="Temsilci İki", region="901", active=True)
            db.session.add_all([product, first, second])
            db.session.flush()
            db.session.add_all([
                Target(year=2042, month=1, quarter="Q1", representative_id=first.id, product_id=product.id, unit_target=100),
                Target(year=2042, month=1, quarter="Q1", representative_id=second.id, product_id=product.id, unit_target=200),
            ])
            upload = IMSUpload(file_name="region.xlsx", year=2042, month=1, quarter="Q1", week_number=5, status="COMPLETED")
            db.session.add(upload)
            db.session.flush()

            def row(territory, brick, name, value, company=False, competitor=False):
                return CompetitionData(
                    upload_id=upload.id, year=2042, month=1, sheet_name="AYLIK REKABET KUTU",
                    period_type="MONTHLY", territory=territory, subterritory=brick,
                    product_group="TRAVAZOL GRUP", product_name=name, metric_type="UNIT",
                    metric_value=value, is_company_product=company, is_competitor=competitor, source_row=value,
                )

            db.session.add_all([
                row("901 DIYARBAKIR", "MARDIN BRICK A", "TRAVAZOL", 120, company=True),
                row("901 DIYARBAKIR", "MARDIN BRICK A", "RAKIP A", 180, competitor=True),
                row("901 DIYARBAKIR", "SIRNAK BRICK B", "RAKIP B", 60, competitor=True),
                row("201 KADIKOY", "BRICK X", "RAKIP X", 999, competitor=True),
            ])
            db.session.commit()

            result = RegionMarketService("901", [first.id, second.id], 2042, 1).build()
            travazol = result["rows"][0]
            assert result["has_data"] is True
            assert travazol["target_unit"] == 300
            assert travazol["company_unit"] == 120
            assert travazol["competitor_unit"] == 240
            assert travazol["market_unit"] == 360
            assert travazol["share_percent"] == 33.3
            assert [item["name"] for item in travazol["rivals"]] == ["RAKIP A", "RAKIP B"]
            assert [item["brick"] for item in result["top_bricks"]] == ["MARDIN BRICK A", "SIRNAK BRICK B"]
            assert result["totals"]["competitor_unit"] == 240
            assert result["available_periods"] == [{"year": 2042, "month": 1, "label": "01/2042"}]
            assert result["rival_rows"][0]["name"] == "RAKIP A"
            assert result["rival_rows"][0]["cities"] == [
                {"city": "MARDIN", "unit": 180.0, "market_unit": 300.0, "share_percent": 60.0}
            ]
            assert result["rival_rows"][1]["cities"] == [
                {"city": "SIRNAK", "unit": 60.0, "market_unit": 60.0, "share_percent": 100.0}
            ]
            assert len(result["rival_groups"]) == 1
            assert result["rival_groups"][0]["product_name"] == "Travazol"
            assert [item["name"] for item in result["rival_groups"][0]["rivals"]] == ["RAKIP A", "RAKIP B"]
            assert result["default_rival_group_id"] == product.id
            assert result["default_rival_key"] == result["rival_groups"][0]["rivals"][0]["pane_key"]
    finally:
        temporary.cleanup()


def test_region_market_panel_is_above_ai_panel_and_has_product_tabs():
    template = (Path(__file__).resolve().parents[1] / "app" / "templates" / "region_performance.html").read_text(encoding="utf-8")
    assert template.index("BÖLGESEL REKABET VE PAZAR MERKEZİ") < template.index('include "partials/scoped_ai_panel.html"')
    assert "data-market-tab" in template
    assert "data-market-pane" in template
    assert "data-rival-tab" in template
    assert "data-rival-pane" in template
    assert "data-rival-group" in template
    assert "data-rival-group-list" in template
    assert "BÖLGESEL RAKİP TOPLAM KUTU ÇIKIŞI" in template


def test_region_product_resolution_prefers_excel_group_over_rival_name():
    service = object.__new__(RegionMarketService)
    acnemix = Product(product_code="ACNEMIX", product_name="Acnemix", competitor_group="ACNEMIX GRUP")
    monurol = Product(product_code="MONUROL", product_name="Monurol", competitor_group="MONUROL GRUP")
    matched = service._product_for("ACNEMIX GRUP", "MONUROL BENZERİ RAKİP", [monurol, acnemix])
    assert matched is acnemix
