from decimal import Decimal

import app.services.april_global_box_period_lock as lock


def test_open_april_national_uses_tl_unit_price_for_every_product(monkeypatch):
    monkeypatch.setattr(lock, "_open_april_period", lambda year, month: True)
    monkeypatch.setattr(lock, "_prices", lambda product_ids: {1: 100, 2: 250})
    payload = {
        "unit_target": 9999,
        "unit_actual": 8888,
        "unit_realization_percent": 0,
        "products": [
            {
                "product_id": 1,
                "target_tl": 1000,
                "actual_tl": 550,
                "unit_target": 900,
                "unit_actual": 700,
            },
            {
                "product_id": 2,
                "target_tl": 2500,
                "actual_tl": 1250,
                "unit_target": 800,
                "unit_actual": 600,
            },
        ],
    }

    result = lock._recalculate_national_payload(payload, 2026, 4)

    assert result["products"][0]["unit_target"] == 10
    assert result["products"][0]["unit_actual"] == 5
    assert result["products"][1]["unit_target"] == 10
    assert result["products"][1]["unit_actual"] == 5
    assert result["unit_target"] == 20
    assert result["unit_actual"] == 10
    assert result["unit_realization_percent"] == 50
    assert result["box_source"] == "IMS_TL_DIV_UNIT_PRICE"


def test_closed_production_period_is_not_recalculated(monkeypatch):
    monkeypatch.setattr(lock, "_open_april_period", lambda year, month: False)
    payload = {
        "unit_target": 750000,
        "unit_actual": 808342,
        "products": [{"product_id": 1, "target_tl": 96234750, "actual_tl": 72368123, "unit_target": 750000, "unit_actual": 808342}],
    }
    snapshot = {
        "unit_target": payload["unit_target"],
        "unit_actual": payload["unit_actual"],
        "product_target": payload["products"][0]["unit_target"],
        "product_actual": payload["products"][0]["unit_actual"],
    }

    result = lock._recalculate_national_payload(payload, 2026, 4)

    assert result["unit_target"] == snapshot["unit_target"]
    assert result["unit_actual"] == snapshot["unit_actual"]
    assert result["products"][0]["unit_target"] == snapshot["product_target"]
    assert result["products"][0]["unit_actual"] == snapshot["product_actual"]
    assert "box_source" not in result


def test_open_region_market_uses_canonical_representative_units(monkeypatch):
    monkeypatch.setattr(lock, "_open_april_period", lambda year, month: True)

    class FakeService:
        year = 2026
        month = 4
        representative_ids = (10, 20)

    def fake_effective(year, month, representative_id, product_ids):
        if representative_id == 10:
            return {1: {"target_unit": Decimal("40"), "actual_unit": Decimal("25")}}
        return {1: {"target_unit": Decimal("60"), "actual_unit": Decimal("35")}}

    monkeypatch.setattr(lock.ProductionResultService, "effective_products", fake_effective)
    payload = {
        "rows": [{"product_id": 1, "target_unit": 999, "company_unit": 777, "market_company_unit": 90, "competitor_unit": 30}],
        "totals": {"company_unit": 90, "effective_company_unit": 777, "competitor_unit": 30, "market_unit": 120},
    }

    result = lock._recalculate_region_market_payload(FakeService(), payload)

    row = result["rows"][0]
    assert row["target_unit"] == 100
    assert row["company_unit"] == 60
    assert row["realization_percent"] == 60
    # Competition market denominator stays on the IMS competition chain.
    assert row["market_company_unit"] == 90
    assert result["totals"]["effective_company_unit"] == 60
    assert result["company_box_source"] == "IMS_TL_DIV_UNIT_PRICE"


def test_lock_contract_declares_closed_period_import_guards():
    source = open("app/services/april_global_box_period_lock.py", encoding="utf-8").read()
    assert "kapalı döneme IMS yüklenemez" in source
    assert "kapalı dönem hedefleri değiştirilemez" in source
    assert "ProductionResultService.final_upload" in source
