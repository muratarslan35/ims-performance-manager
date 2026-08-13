import tempfile
from pathlib import Path

from flask_migrate import upgrade

from app import create_app
from app.extensions import db
from app.models import CompetitionData, IMSSummary, IMSUpload, Product, Representative, RepresentativeBrickAssignment
from app.services.representative_market_service import RepresentativeMarketService


def test_representative_market_analysis_is_brick_scoped_and_keeps_seven_products():
    temporary = tempfile.TemporaryDirectory()
    database_path = Path(temporary.name) / "representative-market.db"

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
            representative = Representative(rep_code="R1", rep_name="Temsilci Bir", active=True)
            other = Representative(rep_code="R2", rep_name="Temsilci İki", active=True)
            names = ("Travazol", "Monurol", "Acnemix", "Mixovul", "Stiderm", "Brimoder", "Fentivag")
            products = [
                Product(product_code=name.upper(), product_name=name, display_order=index, is_active=True)
                for index, name in enumerate(names)
            ]
            db.session.add_all([representative, other, *products])
            db.session.flush()
            upload = IMSUpload(file_name="august.xlsx", year=2026, month=8, quarter="Q3", status="COMPLETED")
            previous_upload = IMSUpload(file_name="july.xlsx", year=2026, month=7, quarter="Q3", status="COMPLETED")
            db.session.add_all([upload, previous_upload])
            db.session.flush()
            db.session.add_all(
                [
                    RepresentativeBrickAssignment(representative_id=representative.id, year=2026, month=8, brick="BRICK A"),
                    RepresentativeBrickAssignment(representative_id=representative.id, year=2026, month=8, brick="BRICK C"),
                    RepresentativeBrickAssignment(representative_id=other.id, year=2026, month=8, brick="BRICK B"),
                    IMSSummary(upload_id=upload.id, representative_id=representative.id, product_id=products[0].id, year=2026, month=8, quarter="Q3", tl=100, unit=10),
                    IMSSummary(upload_id=previous_upload.id, representative_id=representative.id, product_id=products[0].id, year=2026, month=7, quarter="Q3", tl=50, unit=5),
                ]
            )

            def competition(brick, product_name, metric_type, value):
                return CompetitionData(
                    upload_id=upload.id, year=2026, month=8, sheet_name=f"REKABET {metric_type}",
                    period_type="MONTHLY", territory="101", subterritory=brick,
                    product_group="TRAVAZOL GRUBU", product_name=product_name,
                    metric_type=metric_type, metric_value=value, source_row=1,
                )

            db.session.add_all(
                [
                    competition("BRICK A", "TRAVAZOL", "TL", 100),
                    competition("BRICK A", "RAKIP A", "TL", 300),
                    competition("BRICK A", "TRAVAZOL", "UNIT", 10),
                    competition("BRICK A", "RAKIP A", "UNIT", 30),
                    competition("BRICK C", "TRAVAZOL", "UNIT", 5),
                    competition("BRICK C", "RAKIP C", "UNIT", 95),
                    competition("BRICK B", "RAKIP B", "UNIT", 900),
                ]
            )
            db.session.add(CompetitionData(
                upload_id=previous_upload.id, year=2026, month=7, sheet_name="REKABET UNIT",
                period_type="MONTHLY", territory="101", subterritory="BRICK A",
                product_group="TRAVAZOL GRUBU", product_name="RAKIP A",
                metric_type="UNIT", metric_value=20, source_row=1,
            ))
            db.session.commit()

            result = RepresentativeMarketService(representative, 2026, 8).build()

            assert result["scope"] == "brick"
            assert len(result["rows"]) == 7
            travazol = result["rows"][0]
            assert travazol["actual_unit"] == 10
            assert travazol["market_unit"] == 140
            assert travazol["competitor_unit"] == 130
            assert travazol["share_percent"] == 7.1
            assert travazol["has_previous"] is True
            assert travazol["previous_actual_unit"] == 5
            assert travazol["actual_change_unit"] == 5
            assert travazol["actual_change_percent"] == 100.0
            assert travazol["competitor_change_unit"] == 115
            assert travazol["rivals"] == [
                {"name": "RAKIP C", "unit": 95.0},
                {"name": "RAKIP A", "unit": 30.0},
            ]
            assert [row["brick"] for row in result["brick_rows"]] == ["BRICK C", "BRICK A"]
            assert result["brick_rows"][0]["attention"] == "critical"
            assert result["brick_rows"][0]["threats"][0]["product_name"] == "Travazol"
            assert len(result["brick_product_rows"]) == 2
            assert result["brick_product_rows"][0]["product_name"] == "Travazol"
            assert result["brick_product_rows"][0]["company_unit"] == 10
            assert result["brick_product_rows"][0]["market_products"] == [
                {"name": "TRAVAZOL", "unit": 10.0, "is_company": True, "share_percent": 25.0, "realization_percent": None},
                {"name": "RAKIP A", "unit": 30.0, "is_company": False, "share_percent": 75.0, "realization_percent": None},
            ]
    finally:
        temporary.cleanup()
