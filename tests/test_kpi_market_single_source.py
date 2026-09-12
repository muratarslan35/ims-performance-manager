from types import SimpleNamespace

from app.services.kpi_market_single_source import (
    normalize_national_payload,
    normalize_region_payload,
    normalize_representative_payload,
)


def _controls():
    return {
        "TRAVAZOL": {"company": 100.0, "market": 250.0},
        "MONUROL": {"company": 50.0, "market": 200.0},
    }


def test_national_uses_same_company_and_pazar_source():
    payload = {
        "groups": [
            {"company_product": "Travazol", "company_value": 999, "market_value": 20},
            {"company_product": "Monurol", "company_value": 999, "market_value": 20},
        ]
    }
    result = normalize_national_payload(payload, _controls())
    assert result["company_total_unit"] == 150
    assert result["market_total_unit"] == 450
    assert result["competitor_total_unit"] == 300
    assert result["company_total_unit"] + result["competitor_total_unit"] == result["market_total_unit"]
    assert result["groups"][0]["competitor_sales_unit"] == 150
    assert result["groups"][0]["company_share_percent"] == 40


def test_region_replaces_mixed_production_and_detail_totals():
    payload = {
        "rows": [
            {"product_name": "Travazol", "target_unit": 200, "company_unit": 9, "market_unit": 999},
            {"product_name": "Monurol", "target_unit": 100, "company_unit": 8, "market_unit": 999},
        ],
        "totals": {"company_unit": 17, "effective_company_unit": 300, "market_unit": 1998},
    }
    result = normalize_region_payload(payload, _controls(), lambda value: int(round(value)))
    assert result["totals"]["company_unit"] == 150
    assert result["totals"]["effective_company_unit"] == 150
    assert result["totals"]["market_unit"] == 450
    assert result["totals"]["competitor_unit"] == 300
    assert result["rows"][0]["company_unit"] + result["rows"][0]["competitor_unit"] == result["rows"][0]["market_unit"]
    assert result["rows"][0]["realization_percent"] == 50


def test_representative_uses_brick_company_and_pazar_not_production_override():
    travazol = SimpleNamespace(product_name="Travazol")
    monurol = SimpleNamespace(product_name="Monurol")
    payload = {
        "rows": [
            {"product": travazol, "actual_unit": 999, "market_unit": 20, "target_unit": 200},
            {"product": monurol, "actual_unit": 999, "market_unit": 20, "target_unit": 100},
        ],
        "brick_product_rows": [
            {"product_name": "Travazol", "company_unit": 40, "market_unit": 100},
            {"product_name": "Travazol", "company_unit": 60, "market_unit": 150},
            {"product_name": "Monurol", "company_unit": 50, "market_unit": 200},
        ],
    }
    result = normalize_representative_payload(payload)
    assert result["rows"][0]["actual_unit"] == 100
    assert result["rows"][0]["market_unit"] == 250
    assert result["rows"][0]["competitor_unit"] == 150
    assert result["totals"]["actual_unit"] == 150
    assert result["totals"]["market_unit"] == 450
    assert result["totals"]["competitor_unit"] == 300
