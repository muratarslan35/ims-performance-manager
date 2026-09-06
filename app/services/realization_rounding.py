"""Canonical read/display rounding for TL realization percentages.

Business rule:
- fractional part strictly greater than .50000 rounds upward;
- an exact .50000 tie stays at the lower integer;
- values below .50000 stay at the lower integer.

Examples: 125.5004 -> 126, 125.50000 -> 125, 124.499999 -> 124.
The helper intentionally does not mutate target/actual TL values or prime inputs.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR


def _decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or 0))


def round_realization_value(value):
    """Round a non-negative realization percentage to the canonical whole percent."""
    number = _decimal(value)
    if number < 0:
        # Realization is normally non-negative; preserve symmetric behavior if a
        # diagnostic path ever supplies a negative percentage.
        return -round_realization_value(-number)
    lower = number.to_integral_value(rounding=ROUND_FLOOR)
    fraction = number - lower
    return int(lower + (1 if fraction > Decimal("0.5") else 0))


def realization_percent(actual, target):
    """Calculate exact actual/target percentage, then apply canonical rounding."""
    target_value = _decimal(target)
    if not target_value:
        return 0
    exact = _decimal(actual) * Decimal("100") / target_value
    return round_realization_value(exact)
