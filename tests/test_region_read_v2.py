from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app import create_app


def _app(tmp_path):
    class Config:
        TESTING = True
        SECRET_KEY = "region-read-v2"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'region-read-v2.db'}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        LOGIN_DISABLED = True
        UPLOAD_FOLDER = Path(tmp_path) / "uploads"
        REPORT_FOLDER = Path(tmp_path) / "reports"
        BACKUP_FOLDER = Path(tmp_path) / "backups"
        LOG_FOLDER = Path(tmp_path) / "logs"
        TEMP_FOLDER = Path(tmp_path) / "temp"
    return create_app(Config)


def test_region_uses_official_target_minus_balance_when_weekly_actual_missing(tmp_path):
    app = _app(tmp_path)
    from app.extensions import db
    from app.models import IMSRawData, IMSUpload, Product, Representative, Target
    from app.services.official_aggregate_service import TARGET_TYPE
    from app.services.region_performance_service import RegionPerformanceService

    with app.app_context():
        db.create_all()
        product = Product(product_code="R8", product_name="Region 8", is_active=True)
        rep = Representative(rep_code="R901", rep_name="Region Rep", region="901", city="Diyarbakır", active=True)
        db.session.add_all([product, rep]); db.session.flush()
        upload = IMSUpload(file_name="week8.xlsx", year=2026, month=2, week_number=8, status="COMPLETED", completed_at=datetime(2026, 2, 28))
        db.session.add(upload); db.session.flush()
        db.session.add(Target(year=2026, month=2, representative_id=rep.id, product_id=product.id, tl_target=1200, unit_target=12))
        db.session.add_all([
            IMSRawData(upload_id=upload.id, year=2026, month=2, sheet_name="BAKIYE", sheet_type=TARGET_TYPE, source_row=0, product_id=product.id, territory="901", unit=12, tl=1200, raw_json="{}"),
            IMSRawData(upload_id=upload.id, year=2026, month=2, sheet_name="BAKIYE", sheet_type="dashboard_balance_region", source_row=0, product_id=product.id, territory="901", unit=1200, tl=300, raw_json="{}"),
        ])
        db.session.commit()
        monthly = RegionPerformanceService("901", 2026, 2).report()["periods"]["monthly"]
        assert monthly["complete"] is True
        assert monthly["target_tl"] == Decimal("1200.0")
        assert monthly["actual_tl"] == Decimal("900.0")
        assert monthly["realization_percent"] == Decimal("75.00")


def test_representative_period_prefers_persisted_ims_actual_over_corrupt_summary(tmp_path):
    app = _app(tmp_path)
    from app.extensions import db
    from app.models import IMSSummary, IMSUpload, Product, Representative, Target
    from app.services.representative_period_snapshot_service import RepresentativePeriodSnapshotService

    with app.app_context():
        db.create_all()
        product = Product(product_code="W8", product_name="Week8", is_active=True)
        rep = Representative(rep_code="W8R", rep_name="Week8 Rep", active=True)
        db.session.add_all([product, rep]); db.session.flush()
        upload = IMSUpload(file_name="week8.xlsx", year=2026, month=2, week_number=8, status="COMPLETED")
        db.session.add(upload); db.session.flush()
        db.session.add(Target(year=2026, month=2, representative_id=rep.id, product_id=product.id, tl_target=1000, unit_target=10, tl_realization=250, unit_realization=2))
        db.session.add(IMSSummary(upload_id=upload.id, year=2026, month=2, representative_id=rep.id, product_id=product.id, tl=0, unit=999999))
        db.session.commit()
        monthly = RepresentativePeriodSnapshotService.build(rep.id, 2026, 2)["monthly"]
        assert monthly["complete"] is True
        assert monthly["actual_tl"] == Decimal("250")
        assert monthly["realization_percent"] == 25.0


def test_representative_period_preserves_legacy_summary_when_target_actual_unset(tmp_path):
    app = _app(tmp_path)
    from app.extensions import db
    from app.models import IMSSummary, IMSUpload, Product, Representative, Target
    from app.services.representative_period_snapshot_service import RepresentativePeriodSnapshotService

    with app.app_context():
        db.create_all()
        product = Product(product_code="OLD", product_name="Legacy", is_active=True)
        rep = Representative(rep_code="OLDR", rep_name="Legacy Rep", active=True)
        db.session.add_all([product, rep]); db.session.flush()
        upload = IMSUpload(file_name="old.xlsx", year=2025, month=12, status="COMPLETED")
        db.session.add(upload); db.session.flush()
        db.session.add(Target(year=2025, month=12, representative_id=rep.id, product_id=product.id, tl_target=1000, unit_target=10, tl_realization=0))
        db.session.add(IMSSummary(upload_id=upload.id, year=2025, month=12, representative_id=rep.id, product_id=product.id, tl=600, unit=6))
        db.session.commit()
        monthly = RepresentativePeriodSnapshotService.build(rep.id, 2025, 12)["monthly"]
        assert monthly["actual_tl"] == Decimal("600.0")
        assert monthly["realization_percent"] == 60.0


def test_annual_realization_uses_ims_zero_as_real_value(tmp_path):
    app = _app(tmp_path)
    from app.extensions import db
    from app.models import IMSSummary, IMSUpload, Product, Representative, Target
    from app.services.annual_realization_service import AnnualRealizationService

    with app.app_context():
        db.create_all()
        product = Product(product_code="ANN", product_name="Annual", is_active=True)
        rep = Representative(rep_code="ANNR", rep_name="Annual Rep", active=True)
        db.session.add_all([product, rep]); db.session.flush()
        upload = IMSUpload(file_name="annual.xlsx", year=2026, month=2, status="COMPLETED")
        db.session.add(upload); db.session.flush()
        db.session.add(Target(year=2026, month=2, representative_id=rep.id, product_id=product.id, tl_target=1000, tl_realization=400))
        db.session.add(IMSSummary(upload_id=upload.id, year=2026, month=2, representative_id=rep.id, product_id=product.id, tl=0, unit=9999))
        db.session.commit()
        february = AnnualRealizationService.build(2026, [rep.id])[1]
        assert february["actual_tl"] == 0.0
        assert february["percent"] == 0.0
        assert february["source"] == "IMS"


def test_region_periods_use_fixed_h1_while_monthly_keeps_selection(monkeypatch):
    from app.services.region_performance_service import RegionPerformanceService
    service = object.__new__(RegionPerformanceService)
    service.year = 2026
    service.month = 1
    monkeypatch.setattr(service, "_latest_completed_period", lambda: (2026, 2))
    assert service.period_months(1) == [(2026, 1)]
    assert service.period_months(3) == [(2025, 12), (2026, 1), (2026, 2)]
    assert service.period_months(6) == [(2026, 1), (2026, 2)]
    assert service.period_months(None) == [(2026, 1), (2026, 2)]

    monkeypatch.setattr(service, "_latest_completed_period", lambda: (2026, 8))
    assert service.period_months(6) == [
        (2026, 1), (2026, 2), (2026, 3), (2026, 4), (2026, 5), (2026, 6)
    ]


def test_region_product_unit_gap_uses_archived_mf_siz_kutu_balance_not_actual_aggregate(tmp_path, monkeypatch):
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
        monkeypatch.setattr("app.services.region_performance_service.region_balance_units", lambda upload_id, region_key: {product.id: 12.0})
        row = RegionPerformanceService("901", 2026, 2).report()["periods"]["monthly"]["products"][0]
        assert row["target_unit"] == Decimal("100.0")
        assert row["actual_unit"] == Decimal("88.0")
        assert row["unit_difference"] == Decimal("-12.0")


def test_region_product_table_has_unit_gap_and_tl_gap_headers():
    template = Path("app/templates/region_performance.html").read_text(encoding="utf-8")
    assert "<th>Kutu Farkı</th><th>₺ Farkı</th>" in template
    assert "item.unit_difference" in template


def test_region_box_rows_are_embedded_from_prefetched_representative_read_models():
    from app.services.persistent_region_snapshot_service import (
        PersistentRegionSnapshotService,
    )

    report = {
        "periods": {
            "monthly": {
                "representatives": [{
                    "representative_id": 10,
                    "representative_name": "Temsilci A",
                    "city": "Diyarbakır",
                    "active": True,
                    "is_vacant": False,
                }]
            },
            "q3": {
                "representatives": [{
                    "representative_id": 10,
                    "representative_name": "Temsilci A",
                    "city": "Diyarbakır",
                    "active": True,
                    "is_vacant": False,
                }]
            },
        }
    }
    product = {"id": 1, "product_name": "Travazol", "display_order": 1}
    workspaces = {
        10: {
            "snapshots": {
                "monthly": {"products": [{
                    "product": product,
                    "target_unit": 100,
                    "actual_unit": 80,
                }]},
                "q3": {"products": [{
                    "product": product,
                    "target_unit": 300,
                    "actual_unit": 250,
                }]},
            }
        }
    }
    result = PersistentRegionSnapshotService._embed_representative_products(
        report, 2026, 9, workspaces
    )

    assert result["periods"]["monthly"]["representative_products"][0]["target_unit"] == 100
    assert result["periods"]["q3"]["representative_products"][0]["actual_unit"] == 250


def test_region_box_target_matrix_merges_finalized_monthly_rows_without_queries():
    from app.services.period_result_sum_guard import _merge_representative_products

    rows = _merge_representative_products([
        {
            "representative_products": [{
                "representative_id": 10,
                "representative_name": "Temsilci A",
                "city": "Diyarbakır",
                "active": True,
                "is_vacant": False,
                "product_id": 1,
                "product_name": "Travazol",
                "product_display_order": 1,
                "target_unit": 100,
                "actual_unit": 80,
                "unit_complete": True,
            }]
        },
        {
            "representative_products": [{
                "representative_id": 10,
                "representative_name": "Temsilci A",
                "city": "Diyarbakır",
                "active": True,
                "is_vacant": False,
                "product_id": 1,
                "product_name": "Travazol",
                "product_display_order": 1,
                "target_unit": 120,
                "actual_unit": 100,
                "unit_complete": True,
            }]
        },
    ])

    assert len(rows) == 1
    assert rows[0]["target_unit"] == Decimal("220")
    assert rows[0]["actual_unit"] == Decimal("180")
    assert rows[0]["unit_complete"] is True


def test_region_template_places_snapshot_box_matrix_before_market_panel():
    template = Path("app/templates/region_performance.html").read_text(encoding="utf-8")

    assert "Temsilci Kutu Hedef Takibi" in template
    assert 'data-box-period="monthly"' in template
    assert 'data-box-period="quarter"' in template
    assert 'data-box-threshold="75"' in template
    assert 'data-box-threshold="90"' in template
    assert 'data-box-threshold="100"' in template
    assert "representative_products" in template
    assert "data-region-box-target-data" in template
    assert "actual-(target*threshold/100)" in template
    assert template.index("Temsilci Kutu Hedef Takibi") < template.index("BÖLGESEL REKABET VE PAZAR MERKEZİ")

def test_region_box_matrix_controls_and_fixed_layout_contract():
    template = Path("app/templates/region_performance.html").read_text(encoding="utf-8")

    assert "REGION BOX FIXED GRID 20260919m" in template
    assert "table-layout:fixed!important" in template
    assert "overflow:hidden!important" in template
    assert "region-box-filter-stack" in template
    assert template.index('data-box-period="monthly"') < template.index('data-box-threshold="75"')
    assert "Number(a.vacant)-Number(b.vacant)" in template
    assert "row.active!==false" in template
    assert "row.active!==false&&row.is_vacant!==true" not in template

def test_region_box_dark_mode_and_centering_contract():
    template = Path("app/templates/region_performance.html").read_text(encoding="utf-8")

    assert "REGION BOX DARK CENTER POLISH 20260919n" in template
    assert "text-align: center !important" in template
    assert "background: #143d2c !important" in template
    assert "background: #4a2428 !important" in template
    assert "color: #7df0b0 !important" in template
    assert "color: #ffaaa9 !important" in template
    assert "table-layout: fixed !important" in template

def test_region_box_title_left_and_period_controls_centered():
    template = Path("app/templates/region_performance.html").read_text(encoding="utf-8")

    assert "REGION BOX TITLE LEFT PERIOD CENTER 20260919o" in template
    assert "text-align: left !important" in template
    assert "grid-template-columns: minmax(0,1fr) auto minmax(0,1fr) !important" in template
    assert "width: 288px !important" in template
    assert "region-box-toolbar-meta" in template
    assert template.index('data-box-period="monthly"') < template.index('data-box-threshold="75"')

def test_historical_region_uses_durable_compatibility_read_model_when_exact_snapshot_missing(monkeypatch):
    import app.regions as regions

    monkeypatch.setattr(
        regions.PersistentRegionSnapshotService,
        "source_identity",
        classmethod(lambda cls, year, month: (44, 9)),
    )
    monkeypatch.setattr(
        regions.PersistentRegionSnapshotService,
        "get_active_for_visible_upload",
        classmethod(lambda cls, region_key, year, month, source_upload_id: None),
    )
    expected = {
        "report": {
            "region_key": "901",
            "region_name": "901 DIYARBAKIR",
            "periods": {"monthly": {"target_tl": 100, "actual_tl": 80}},
        },
        "market_analysis": {"products": []},
        "ai_report": {"scope": "901 DIYARBAKIR"},
    }
    monkeypatch.setattr(
        regions.HistoricalRegionReadModelService,
        "get_active",
        classmethod(lambda cls, region_key, year, month: expected),
    )

    payload, source = regions._region_read_model(
        "901", 2026, 7, source_upload_id=None
    )

    assert source == "compatibility"
    assert payload["report"]["periods"]["monthly"]["actual_tl"] == 80
    assert payload["ai_report"]["scope"] == "901 DIYARBAKIR"


def test_historical_region_compatibility_builds_once_per_source_identity(tmp_path, monkeypatch):
    app = _app(tmp_path)
    from app.services.historical_region_read_model_service import (
        HistoricalRegionReadModelService,
    )
    from app.services.persistent_region_snapshot_service import (
        PersistentRegionSnapshotService,
    )

    calls = []
    monkeypatch.setattr(
        PersistentRegionSnapshotService,
        "source_identity",
        classmethod(lambda cls, year, month: (44, 9)),
    )
    monkeypatch.setattr(
        HistoricalRegionReadModelService,
        "_build_authoritative",
        classmethod(
            lambda cls, region_key, year, month: (
                calls.append((region_key, year, month))
                or {
                    "report": {
                        "region_key": region_key,
                        "region_name": "901 DIYARBAKIR",
                        "periods": {},
                    },
                    "market_analysis": {},
                    "ai_report": {},
                }
            )
        ),
    )

    with app.app_context():
        first = HistoricalRegionReadModelService.get_or_build("901", 2026, 4)
        second = HistoricalRegionReadModelService.get_or_build("901", 2026, 4)

    assert first == second
    assert calls == [("901", 2026, 4)]


def test_active_region_stays_snapshot_gated_when_exact_snapshot_missing(monkeypatch):
    import app.regions as regions

    monkeypatch.setattr(
        regions.PersistentRegionSnapshotService,
        "get_active_for_visible_upload",
        classmethod(lambda cls, region_key, year, month, source_upload_id: None),
    )
    monkeypatch.setattr(
        regions.PersistentRegionSnapshotService,
        "get_active",
        classmethod(lambda cls, region_key, year, month: None),
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("active period must not run historical compatibility calculation")

    monkeypatch.setattr(
        regions.HistoricalRegionReadModelService,
        "get_or_build",
        classmethod(lambda cls, *args, **kwargs: forbidden(*args, **kwargs)),
    )

    payload, source = regions._region_read_model(
        "901", 2026, 9, source_upload_id=50
    )

    assert payload is None
    assert source == "unavailable"


def test_snapshot_region_ai_is_finalized_once_with_historical_compatibility_fallback():
    route = Path("app/regions.py").read_text(encoding="utf-8")
    snapshot_service = Path("app/services/persistent_region_snapshot_service.py").read_text(encoding="utf-8")
    partial = Path("app/templates/partials/scoped_ai_panel.html").read_text(encoding="utf-8")
    service = Path("app/services/region_ai_snapshot_service.py").read_text(encoding="utf-8")

    assert "PersistentRepresentativeSnapshotService.get_active_many" not in route
    assert "RegionAISnapshotService.build" not in route
    assert "PersistentRegionSnapshotService.enrich_for_period" not in route
    assert "_compatibility_region_read_model" in route
    assert "HistoricalRegionReadModelService.get_active" in route
    assert "HistoricalRegionReadModelService.get_or_build" not in route
    assert "RegionPerformanceService(" not in route
    assert "RegionMarketService(" not in route
    assert 'region_data_source == "read-model"' in route
    assert "PersistentDashboardSnapshotService.get_generation_for_source" in snapshot_service
    assert "PersistentRepresentativeSnapshotService.get_exact_active_many" in snapshot_service
    assert "PersistentRepresentativeSnapshotService.get_active_many" in snapshot_service
    assert "RegionAISnapshotService.build" in snapshot_service
    assert "current_region_workspaces" in snapshot_service
    assert "previous_region_workspaces" in snapshot_service
    assert 'enriched["read_model_version"] = cls.READ_MODEL_VERSION' in snapshot_service
    assert "upgrade_national_realizations_for_period" not in route
    assert "_embed_national_product_realizations" in snapshot_service
    assert "Snapshot-only · 4 alan" not in partial
    assert "NATIONAL altında kalan ürünler" in partial
    assert "Rakip satışı var, şirket çıkışı yok" in partial
    assert "Rakip yoğunluğunu koruyan / artıran iller" in partial
    assert "Rakibin satış kaybettiği brickler" in partial
    assert "Bu ay bölge müdürünün kontrol edeceği 7 sinyal" not in partial
    assert "PUBLISHED_SNAPSHOTS_ONLY" in service
    assert "from app.extensions import db" not in service
    assert "RegionMarketService(" not in service
    assert "DashboardService(" not in service


def test_region_box_embedding_reuses_prefetched_representative_read_models():
    from app.services.persistent_region_snapshot_service import (
        PersistentRegionSnapshotService,
    )

    report = {
        "periods": {
            "monthly": {
                "representatives": [{
                    "representative_id": 10,
                    "representative_name": "Temsilci A",
                    "city": "Diyarbakır",
                    "active": True,
                    "is_vacant": False,
                }]
            },
            "q3": {
                "representatives": [{
                    "representative_id": 10,
                    "representative_name": "Temsilci A",
                    "city": "Diyarbakır",
                    "active": True,
                    "is_vacant": False,
                }]
            },
        }
    }
    workspaces = {
        10: {
            "snapshots": {
                "monthly": {"products": [{
                    "product": {"id": 1, "product_name": "Travazol", "display_order": 1},
                    "target_unit": 100,
                    "actual_unit": 80,
                }]},
                "q3": {"products": [{
                    "product": {"id": 1, "product_name": "Travazol", "display_order": 1},
                    "target_unit": 300,
                    "actual_unit": 250,
                }]},
            }
        }
    }

    result = PersistentRegionSnapshotService._embed_representative_products(
        report, 2026, 9, workspaces
    )

    assert result["periods"]["monthly"]["representative_products"][0]["actual_unit"] == 80
    assert result["periods"]["q3"]["representative_products"][0]["actual_unit"] == 250


def test_open_ims_monthly_region_box_difference_does_not_require_rep_unit_baseline(monkeypatch):
    from app.services.region_box_authority_guard import (
        _apply_direct_monthly_box_authority,
    )
    from app.services.product_unit_price_service import ProductUnitPriceService

    class Service:
        @staticmethod
        def _official_ims_region_month(year, month):
            assert (year, month) == (2026, 9)
            return {
                1: [Decimal("6466975"), Decimal("5584308"), True],
                2: [Decimal("3063433"), Decimal("2653883"), True],
            }

    monkeypatch.setattr(
        ProductUnitPriceService,
        "price_map",
        classmethod(lambda cls, product_ids, year, month: {1: 100, 2: 50}),
    )
    payload = {
        "products": [
            {
                "product_id": 1,
                "target_unit": Decimal("0"),
                "actual_unit": None,
                "unit_complete": False,
                "unit_difference": None,
            },
            {
                "product_id": 2,
                "target_unit": Decimal("0"),
                "actual_unit": None,
                "unit_complete": False,
                "unit_difference": None,
            },
        ]
    }

    result = _apply_direct_monthly_box_authority(Service(), payload, 2026, 9)

    first, second = result["products"]
    assert first["target_unit"] == Decimal("64670")
    assert first["actual_unit"] == Decimal("55843")
    assert first["unit_difference"] == Decimal("-8827")
    assert first["unit_complete"] is True
    assert first["box_authority"] == "REGION_TL_PERIOD_PRICE"
    assert second["target_unit"] == Decimal("61269")
    assert second["actual_unit"] == Decimal("53078")
    assert second["unit_difference"] == Decimal("-8191")
    assert second["unit_complete"] is True


def test_direct_monthly_region_box_repair_keeps_healthy_rows_unchanged(monkeypatch):
    from app.services.region_box_authority_guard import (
        _apply_direct_monthly_box_authority,
    )
    from app.services.product_unit_price_service import ProductUnitPriceService

    class Service:
        @staticmethod
        def _official_ims_region_month(year, month):
            return {1: [Decimal("1000"), Decimal("500"), True]}

    monkeypatch.setattr(
        ProductUnitPriceService,
        "price_map",
        classmethod(lambda cls, product_ids, year, month: {1: 10}),
    )
    original = {
        "product_id": 1,
        "target_unit": Decimal("100"),
        "actual_unit": Decimal("80"),
        "unit_complete": True,
        "unit_difference": Decimal("-20"),
        "box_authority": "EXISTING_AUTHORITY",
    }
    payload = {"products": [dict(original)]}

    result = _apply_direct_monthly_box_authority(Service(), payload, 2026, 9)

    assert result["products"][0] == original
