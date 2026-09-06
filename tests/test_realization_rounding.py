from decimal import Decimal

from app.services.realization_rounding import realization_percent, round_realization_value
from app.services.realization_rounding_guard import normalize_realization_payload


def test_exact_half_stays_lower_integer():
    assert round_realization_value(Decimal("125.50000")) == 125
    assert round_realization_value(Decimal("0.50000")) == 0


def test_fraction_strictly_above_half_rounds_up():
    assert round_realization_value(Decimal("125.5004")) == 126
    assert round_realization_value(Decimal("99.5000001")) == 100


def test_fraction_below_half_stays_lower_integer():
    assert round_realization_value(Decimal("124.499999")) == 124
    assert round_realization_value(Decimal("125.4999")) == 125


def test_realization_is_calculated_from_exact_target_actual_before_rounding():
    assert realization_percent(Decimal("125.5004"), Decimal("100")) == 126
    assert realization_percent(Decimal("125.5"), Decimal("100")) == 125


def test_live_payload_normalization_recalculates_tl_realization_only():
    payload = {
        "target_tl": Decimal("100"),
        "actual_tl": Decimal("125.5004"),
        "realization_percent": 125.5,
        "unit_realization_percent": 88.75,
        "products": [
            {"target_tl": 100, "actual_tl": 124.499999, "realization_percent": 124.5}
        ],
    }
    normalize_realization_payload(payload)
    assert payload["realization_percent"] == 126
    assert payload["unit_realization_percent"] == 88.75
    assert payload["products"][0]["realization_percent"] == 124
