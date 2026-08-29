from pathlib import Path
from types import SimpleNamespace

from app import create_app


def _app(tmp_path):
    class Config:
        TESTING = True
        SECRET_KEY = "region-market-share-authority"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'region-market-share-authority.db'}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        LOGIN_DISABLED = True
        UPLOAD_FOLDER = Path(tmp_path) / "uploads"
        REPORT_FOLDER = Path(tmp_path) / "reports"
        BACKUP_FOLDER = Path(tmp_path) / "backups"
        LOG_FOLDER = Path(tmp_path) / "logs"
        TEMP_FOLDER = Path(tmp_path) / "temp"
    return create_app(Config)


def _competition_row(upload_id, product, name, value, *, metric_type="UNIT", sheet="AYLIK REKABET KUTU", territory="901 DIYARBAKIR", subterritory="MARDIN BRICK A", company=False, competitor=False):
    from app.models import CompetitionData
    return CompetitionData(
        upload_id=upload_id,
        year=2026,
        month=2,
        sheet_name=sheet,
        period_type="MONTHLY",
        territory=territory,
        subterritory=subterritory,
        product_group="TRAVAZOL GRUP",
        product_name=name,
        metric_type=metric_type,
        metric_value=value,
        is_company_product=company,
        is_competitor=competitor,
        source_row=118,
    )


def test_integer_pp_display_matches_workbook_cells_without_redistribution():
    from app.services.region_market_service import RegionMarketService

    assert RegionMarketService._display_integer(3.49) == 3
    assert RegionMarketService._display_integer(3.50) == 3
    assert RegionMarketService._display_integer(3.51) == 4
    assert RegionMarketService._display_integer(5.526297) == 6

    # Real January/Diyarbakir workbook examples: every visible cell is rounded
    # from its own exact PP. Do not steal/add a point to force the visible
    # components to 100; the workbook subtotal is a separate 100 cell.
    allocated = RegionMarketService._allocate_tenth_shares([
        ("MONUROL", 22.500530029984553),
        ("UROCARE", 28.645849108035254),
        ("UROMISIN", 48.85362086198019),
    ])
    assert allocated == {"MONUROL": 23, "UROCARE": 29, "UROMISIN": 49}
    assert sum(allocated.values()) == 101
    assert RegionMarketService._display_integer(33.57540382788109) == 34
    assert RegionMarketService._display_integer(16.41132653600296) == 16


def test_region_market_uses_authoritative_tts_pp_and_keeps_separate_subtotal(tmp_path):
    app = _app(tmp_path)
    from app.extensions import db
    from app.models import IMSUpload, Product, Representative, Target
    from app.services.region_market_service import RegionMarketService

    with app.app_context():
        db.create_all()
        product = Product(
            product_code="TRAVAZOL", product_name="Travazol", ims_name="TRAVAZOL KREM",
            competitor_group="TRAVAZOL GRUP", display_order=1, is_active=True,
        )
        rep = Representative(rep_code="901R", rep_name="Diyarbakır Rep", region="901", active=True)
        db.session.add_all([product, rep]); db.session.flush()
        db.session.add(Target(year=2026, month=2, representative_id=rep.id, product_id=product.id, unit_target=74907))
        upload = IMSUpload(file_name="week9.xlsx", year=2026, month=2, week_number=9, status="COMPLETED")
        db.session.add(upload); db.session.flush()

        db.session.add_all([
            _competition_row(upload.id, product, "TRAVAZOL KREM", 90800, company=True),
            _competition_row(upload.id, product, "ZALAIN", 17975, competitor=True),
            _competition_row(upload.id, product, "TRACOVOL KREM", 6999, competitor=True),
            _competition_row(upload.id, product, "FUGGY", 1964, competitor=True),
            _competition_row(upload.id, product, "MANTAZOL KREM", 1407, competitor=True),
            _competition_row(upload.id, product, "TRAVOCORT KREM", 1789, competitor=True),
            _competition_row(upload.id, product, "TROSYD KREM", 5715, competitor=True),
            _competition_row(upload.id, product, "TRAVAZOL KREM", 71.69420998191853, metric_type="MARKET_SHARE", sheet="TTS REKABET PP", subterritory="901 DIYARBAKIR", company=True),
            _competition_row(upload.id, product, "ZALAIN", 14.1927689914646, metric_type="MARKET_SHARE", sheet="TTS REKABET PP", subterritory="901 DIYARBAKIR", competitor=True),
            _competition_row(upload.id, product, "TRACOVOL KREM", 5.526297088804491, metric_type="MARKET_SHARE", sheet="TTS REKABET PP", subterritory="901 DIYARBAKIR", competitor=True),
            _competition_row(upload.id, product, "FUGGY", 1.5507426035736562, metric_type="MARKET_SHARE", sheet="TTS REKABET PP", subterritory="901 DIYARBAKIR", competitor=True),
            _competition_row(upload.id, product, "MANTAZOL KREM", 1.1109444211955877, metric_type="MARKET_SHARE", sheet="TTS REKABET PP", subterritory="901 DIYARBAKIR", competitor=True),
            _competition_row(upload.id, product, "TRAVOCORT KREM", 1.4125654367582847, metric_type="MARKET_SHARE", sheet="TTS REKABET PP", subterritory="901 DIYARBAKIR", competitor=True),
            _competition_row(upload.id, product, "TROSYD KREM", 4.51247147628485, metric_type="MARKET_SHARE", sheet="TTS REKABET PP", subterritory="901 DIYARBAKIR", competitor=True),
            _competition_row(upload.id, product, "TRAVAZOL GRUBU (KREM PAZARI) SUBTOTAL", 100.0, metric_type="MARKET_SHARE", sheet="TTS REKABET PP", subterritory="901 DIYARBAKIR"),
        ])
        db.session.commit()

        result = RegionMarketService("901", [rep.id], 2026, 2).build()
        row = next(item for item in result["rows"] if item["product_name"] == "Travazol")
        tracovol = next(item for item in row["rivals"] if item["name"] == "TRACOVOL KREM")

        assert row["market_share_source"] == "IMS_TTS_REKABET_PP"
        assert row["precise_share_percent"] == 71.69421
        assert tracovol["precise_market_share_percent"] == 5.526297
        assert tracovol["market_share_percent"] == 6
        assert row["display_share_total"] == 100
        assert row["share_percent"] + sum(item["market_share_percent"] for item in row["rivals"]) == 101
        assert result["market_share_source"] == "IMS_TTS_REKABET_PP_WITH_UNIT_FALLBACK"


def test_region_market_does_not_mix_production_actual_into_ims_market_denominator(tmp_path, monkeypatch):
    app = _app(tmp_path)
    from app.extensions import db
    from app.models import IMSUpload, Product, Representative, Target
    from app.services.region_market_service import RegionMarketService

    with app.app_context():
        db.create_all()
        product = Product(
            product_code="TRAVAZOL", product_name="Travazol", ims_name="TRAVAZOL KREM",
            competitor_group="TRAVAZOL GRUP", display_order=1, is_active=True,
        )
        rep = Representative(rep_code="MIXR", rep_name="Mix Rep", region="901", active=True)
        db.session.add_all([product, rep]); db.session.flush()
        db.session.add(Target(year=2026, month=2, representative_id=rep.id, product_id=product.id, unit_target=250))
        upload = IMSUpload(file_name="week9.xlsx", year=2026, month=2, week_number=9, status="COMPLETED")
        db.session.add(upload); db.session.flush()
        db.session.add_all([
            _competition_row(upload.id, product, "TRAVAZOL KREM", 120, company=True),
            _competition_row(upload.id, product, "RAKIP A", 80, competitor=True),
        ])
        db.session.commit()

        service = RegionMarketService("901", [rep.id], 2026, 2)
        monkeypatch.setattr(service, "_official_products", lambda _: {
            product.id: SimpleNamespace(actual_unit=200, target_unit=250)
        })
        result = service._build(upload.id, 999)
        row = next(item for item in result["rows"] if item["product_id"] == product.id)

        assert row["company_unit"] == 200
        assert row["market_company_unit"] == 120
        assert row["market_unit"] == 200
        assert row["share_percent"] == 60
        assert row["realization_percent"] == 80.0


def test_zero_ims_company_unit_does_not_fall_back_to_production(tmp_path, monkeypatch):
    app = _app(tmp_path)
    from app.extensions import db
    from app.models import IMSUpload, Product, Representative, Target
    from app.services.region_market_service import RegionMarketService

    with app.app_context():
        db.create_all()
        product = Product(
            product_code="ZERO", product_name="Travazol", ims_name="TRAVAZOL KREM",
            competitor_group="TRAVAZOL GRUP", display_order=1, is_active=True,
        )
        rep = Representative(rep_code="ZEROR", rep_name="Zero Rep", region="901", active=True)
        db.session.add_all([product, rep]); db.session.flush()
        db.session.add(Target(year=2026, month=2, representative_id=rep.id, product_id=product.id, unit_target=100))
        upload = IMSUpload(file_name="week9.xlsx", year=2026, month=2, week_number=9, status="COMPLETED")
        db.session.add(upload); db.session.flush()
        db.session.add_all([
            _competition_row(upload.id, product, "TRAVAZOL KREM", 0, company=True),
            _competition_row(upload.id, product, "RAKIP A", 50, competitor=True),
        ])
        db.session.commit()

        service = RegionMarketService("901", [rep.id], 2026, 2)
        monkeypatch.setattr(service, "_official_products", lambda _: {
            product.id: SimpleNamespace(actual_unit=75, target_unit=100)
        })
        result = service._build(upload.id, 999)
        row = next(item for item in result["rows"] if item["product_id"] == product.id)
        assert row["company_unit"] == 75
        assert row["market_company_unit"] == 0
        assert row["market_unit"] == 50
        assert row["share_percent"] == 0
