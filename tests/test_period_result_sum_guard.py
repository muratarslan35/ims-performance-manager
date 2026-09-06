from decimal import Decimal

from app.services.period_result_sum_guard import _merge_monthly_payloads


def _month(year, month, *, target_tl, actual_tl, target_unit, actual_unit, unit_difference):
    gap_tl = Decimal(str(target_tl)) - Decimal(str(actual_tl))
    return {
        "target_tl": Decimal(str(target_tl)),
        "actual_tl": Decimal(str(actual_tl)),
        "realization_percent": Decimal(str(actual_tl)) * Decimal("100") / Decimal(str(target_tl)),
        "gap_tl": gap_tl,
        "complete": True,
        "products": [{
            "product_id": 1,
            "product_name": "Travazol",
            "target_tl": Decimal(str(target_tl)),
            "actual_tl": Decimal(str(actual_tl)),
            "gap_tl": gap_tl,
            "target_unit": Decimal(str(target_unit)),
            "actual_unit": Decimal(str(actual_unit)),
            "unit_difference": Decimal(str(unit_difference)),
            "complete": True,
            "unit_complete": True,
            "quota_exit": False,
            "quota_exit_months": [],
        }],
        "representatives": [],
        "months": [{"year": year, "month": month, "label": f"{month:02d}/{year}", "complete": True}],
        "source_by_month": {(year, month): "IMS"},
    }


def test_multi_month_product_uses_sum_of_finalized_month_results():
    march = _month(2026, 3, target_tl="1000", actual_tl="900", target_unit="10", actual_unit="9", unit_difference="-1")
    april = _month(2026, 4, target_tl="2200", actual_tl="1980", target_unit="11", actual_unit="9", unit_difference="-2")

    result = _merge_monthly_payloads([(2026, 3), (2026, 4)], [march, april])
    row = result["products"][0]

    assert result["target_tl"] == Decimal("3200")
    assert result["actual_tl"] == Decimal("2880")
    assert result["gap_tl"] == Decimal("320")
    assert row["target_unit"] == Decimal("21")
    assert row["actual_unit"] == Decimal("18")
    assert row["unit_difference"] == Decimal("-3")
    assert row["gap_tl"] == Decimal("320")
    assert len(result["months"]) == 2


def test_incomplete_month_keeps_period_actuals_incomplete():
    complete = _month(2026, 3, target_tl="1000", actual_tl="900", target_unit="10", actual_unit="9", unit_difference="-1")
    incomplete = _month(2026, 4, target_tl="2000", actual_tl="0", target_unit="10", actual_unit="0", unit_difference="-10")
    incomplete["complete"] = False
    incomplete["actual_tl"] = None
    incomplete["gap_tl"] = None
    incomplete["products"][0]["complete"] = False
    incomplete["products"][0]["actual_tl"] = None
    incomplete["products"][0]["gap_tl"] = None

    result = _merge_monthly_payloads([(2026, 3), (2026, 4)], [complete, incomplete])
    row = result["products"][0]

    assert result["complete"] is False
    assert result["actual_tl"] is None
    assert result["gap_tl"] is None
    assert row["complete"] is False
    assert row["actual_tl"] is None
    assert row["gap_tl"] is None


def test_empty_pre_history_month_does_not_invalidate_period():
    empty = {
        "target_tl": Decimal("0"),
        "actual_tl": None,
        "realization_percent": None,
        "gap_tl": None,
        "complete": False,
        "products": [],
        "representatives": [],
        "months": [{"year": 2025, "month": 12, "label": "12/2025", "complete": True}],
        "source_by_month": {(2025, 12): "REPRESENTATIVE_AGGREGATE"},
    }
    january = _month(2026, 1, target_tl="1000", actual_tl="900", target_unit="10", actual_unit="9", unit_difference="-1")

    result = _merge_monthly_payloads([(2025, 12), (2026, 1)], [empty, january])

    assert result["complete"] is True
    assert result["target_tl"] == Decimal("1000")
    assert result["actual_tl"] == Decimal("900")
    assert result["gap_tl"] == Decimal("100")
    assert result["products"][0]["unit_difference"] == Decimal("-1")
    assert len(result["months"]) == 2
