from app.services.period_result_sum_guard import (
    _compose_region_half_year_snapshot,
    _compose_representative_half_year_workspace,
)
from app.services.realization_rounding import realization_percent


def _region_period(months, target, actual, target_unit, actual_unit):
    return {
        "target_tl": target,
        "actual_tl": actual,
        "gap_tl": target - actual,
        "complete": True,
        "products": [{
            "product_id": 1,
            "product_name": "Travazol",
            "target_tl": target,
            "actual_tl": actual,
            "gap_tl": target - actual,
            "target_unit": target_unit,
            "actual_unit": actual_unit,
            "unit_difference": actual_unit - target_unit,
            "complete": True,
            "unit_complete": True,
            "quota_exit": False,
            "quota_exit_months": [],
        }],
        "representatives": [],
        "months": [
            {"year": 2026, "month": month, "target_tl": target / len(months), "actual_tl": actual / len(months)}
            for month in months
        ],
        "source_by_month": {f"2026|{month}": "OFFICIAL_REGION_SUBTOTAL" for month in months},
    }


def _rep_market(months, actual, market, rival):
    return {
        "scope": "brick",
        "rows": [{
            "product": {"id": 1, "product_name": "Travazol", "display_order": 1},
            "actual_unit": actual,
            "market_unit": market,
            "competitor_unit": market - actual,
            "target_unit": actual + 10,
            "rivals": [{"name": "Rival A", "unit": rival}],
        }],
        "chart_rows": [],
        "brick_product_rows": [{"brick": "A", "product_name": "Travazol", "company_unit": actual}],
        "period_months": [{"year": 2026, "month": month} for month in months],
        "totals": {
            "actual_unit": actual,
            "market_unit": market,
            "competitor_unit": market - actual,
            "share_percent": round(actual * 100 / market, 1),
        },
    }


def _rep_period(months, target, actual, target_unit, actual_unit):
    return {
        "months": [[2026, month] for month in months],
        "products": [{
            "product": {"id": 1, "product_name": "Travazol", "display_order": 1},
            "target_tl": target,
            "actual_tl": actual,
            "target_unit": target_unit,
            "actual_unit": actual_unit,
            "remaining_tl": max(target - actual, 0),
            "source": "IMS",
            "percent": realization_percent(actual, target),
        }],
        "totals": {
            "target_tl": target,
            "actual_tl": actual,
            "target_unit": target_unit,
            "actual_unit": actual_unit,
            "remaining_tl": max(target - actual, 0),
            "percent": realization_percent(actual, target),
        },
        "assignments": [{"brick": f"B{months[-1]}"}],
        "market_analysis": _rep_market(months, actual_unit, actual_unit + 100, 100),
        "has_production_result": False,
        "result_source_label": "Seçili IMS dönemine kadar",
        "ai_report": {
            "scope_type": "representative",
            "scope_name": "TEST REP",
            "competitive_intelligence": {},
        },
    }


def test_region_persisted_h1_is_derived_from_q1_plus_q2_without_mutating_quarters():
    q1 = _region_period([1, 2, 3], 300, 240, 30, 24)
    q2 = _region_period([4, 5, 6], 600, 540, 60, 54)
    snapshot = {"report": {"periods": {"q1": q1, "q2": q2, "half_year": {"target_tl": 999}}}}

    result = _compose_region_half_year_snapshot(snapshot)
    h1 = result["report"]["periods"]["half_year"]

    assert [row["month"] for row in h1["months"]] == [1, 2, 3, 4, 5, 6]
    assert h1["month_count"] == 6
    assert float(h1["target_tl"]) == 900
    assert float(h1["actual_tl"]) == 780
    assert h1["realization_percent"] == realization_percent(780, 900)
    assert float(h1["products"][0]["target_unit"]) == 90
    assert float(h1["products"][0]["actual_unit"]) == 78
    assert result["report"]["periods"]["q1"] is q1
    assert result["report"]["periods"]["q2"] is q2


def test_representative_persisted_h1_uses_existing_quarters_and_terminal_q2_scope():
    q1 = _rep_period([1, 2, 3], 300, 240, 30, 24)
    q2 = _rep_period([4, 5, 6], 600, 540, 60, 54)
    workspace = {"snapshots": {"q1": q1, "q2": q2, "half_year": {"totals": {"target_tl": 999}}}}

    result = _compose_representative_half_year_workspace(workspace)
    h1 = result["snapshots"]["half_year"]

    assert h1["months"] == [[2026, 1], [2026, 2], [2026, 3], [2026, 4], [2026, 5], [2026, 6]]
    assert h1["totals"]["target_tl"] == 900
    assert h1["totals"]["actual_tl"] == 780
    assert h1["totals"]["percent"] == realization_percent(780, 900)
    assert h1["products"][0]["target_unit"] == 90
    assert h1["products"][0]["actual_unit"] == 78
    assert h1["assignments"] == [{"brick": "B6"}]
    assert h1["market_analysis"]["period_months"] == [
        {"year": 2026, "month": month} for month in range(1, 7)
    ]
    assert h1["market_analysis"]["rows"][0]["actual_unit"] == 78
    assert h1["market_analysis"]["rows"][0]["market_unit"] == 278
    assert h1["market_analysis"]["rows"][0]["rivals"] == [{"name": "Rival A", "unit": 200.0}]
    assert "half_year" in h1["ai_report"]["periods"]
    assert result["snapshots"]["q1"] is q1
    assert result["snapshots"]["q2"] is q2
