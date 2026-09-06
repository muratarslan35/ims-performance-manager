from decimal import Decimal

from app.services.period_result_sum_guard import _merge_monthly_payloads, _quarter_months


def _payload(year, month, target, actual):
    target = Decimal(str(target))
    actual = Decimal(str(actual))
    return {
        "target_tl": target,
        "actual_tl": actual,
        "gap_tl": target - actual,
        "complete": True,
        "products": [],
        "representatives": [],
        "months": [{
            "year": year,
            "month": month,
            "label": f"{month:02d}/{year}",
            "target_tl": target,
            "actual_tl": actual,
            "realization_percent": actual * Decimal("100") / target if target else Decimal("0"),
        }],
        "source_by_month": {(year, month): "IMS"},
    }


def test_quarters_are_calendar_fixed_not_rolling_windows():
    assert _quarter_months(2026, 1) == [(2026, 1), (2026, 2), (2026, 3)]
    assert _quarter_months(2026, 2) == [(2026, 4), (2026, 5), (2026, 6)]
    assert _quarter_months(2026, 3) == [(2026, 7), (2026, 8), (2026, 9)]
    assert _quarter_months(2026, 4) == [(2026, 10), (2026, 11), (2026, 12)]


def test_quarter_total_is_sum_of_finalized_month_results():
    months = _quarter_months(2026, 1)
    payloads = [
        _payload(2026, 1, "100", "90"),
        _payload(2026, 2, "200", "220"),
        _payload(2026, 3, "300", "270"),
    ]
    result = _merge_monthly_payloads(months, payloads)
    assert result["target_tl"] == Decimal("600")
    assert result["actual_tl"] == Decimal("580")
    assert result["gap_tl"] == Decimal("20")
    assert result["realization_percent"] == Decimal("580") * Decimal("100") / Decimal("600")


def test_partial_current_quarter_uses_only_available_months():
    months = [(2026, 4)]
    result = _merge_monthly_payloads(months, [_payload(2026, 4, "250", "225")])
    assert result["target_tl"] == Decimal("250")
    assert result["actual_tl"] == Decimal("225")
    assert [row["month"] for row in result["months"]] == [4]
