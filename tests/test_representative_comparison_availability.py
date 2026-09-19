from pathlib import Path

from app.services.representative_comparison_availability_guard import (
    previous_rival_data_available,
)


def test_previous_company_data_does_not_fake_rival_comparison():
    rows = [
        {
            "previous_actual_unit": 20,
            "actual_unit": 12,
            "actual_change_unit": -8,
            "previous_competitor_unit": 0,
            "competitor_unit": 256,
            "competitor_change_unit": 256,
        },
        {
            "previous_actual_unit": 15,
            "actual_unit": 18,
            "actual_change_unit": 3,
            "previous_competitor_unit": 0,
            "competitor_unit": 40,
            "competitor_change_unit": 40,
        },
    ]

    assert previous_rival_data_available(rows) is False


def test_previous_rival_data_is_available_when_any_real_output_exists():
    rows = [
        {"previous_competitor_unit": 0},
        {"previous_competitor_unit": 80},
    ]

    assert previous_rival_data_available(rows) is True


def test_template_shows_waiting_text_for_missing_previous_rival_data():
    template = Path("app/templates/partials/representative_period_panel.html").read_text(
        encoding="utf-8"
    )
    assert "previous_competitor_available" in template
    assert "Veri bekleniyor" in template


def test_monthly_comparison_uses_effective_company_boxes_and_matched_rival_months(monkeypatch):
    from types import SimpleNamespace
    import app.services.representative_period_workspace as workspace

    product = SimpleNamespace(id=1, product_name="Travazol")
    representative = SimpleNamespace(id=97)

    current_products = [{
        "product": product,
        "actual_unit": 2945,
        "source": "IMS",
    }]
    current_market = {
        "has_competition": True,
        "rows": [{
            "product": product,
            # Deliberately different: this is the market/KPI own-box value and
            # must not replace the P2>P1>IMS company result in the comparison.
            "actual_unit": 4070,
            "competitor_unit": 1998,
            "market_unit": 6068,
        }],
    }
    previous_products = [{
        "product": product,
        "actual_unit": 8818,
        "source": "IMS",
    }]
    previous_market = {
        "has_competition": True,
        "rows": [{
            "product": product,
            "actual_unit": 12669,
            "competitor_unit": 4050,
            "market_unit": 16719,
        }],
    }

    monkeypatch.setattr(
        workspace,
        "_aggregate_sales",
        lambda *args, **kwargs: (previous_products, {}, [], {"IMS"}),
    )
    monkeypatch.setattr(
        workspace,
        "_aggregate_market",
        lambda *args, **kwargs: previous_market,
    )

    rows = workspace._monthly_comparison_rows(
        representative,
        2026,
        9,
        current_products,
        current_market,
        sales_cache={},
        assignment_cache={},
        market_cache={},
    )

    row = rows[0]
    assert row["previous_actual_unit"] == 8818
    assert row["actual_unit"] == 2945
    assert row["actual_change_unit"] == -5873
    assert row["actual_change_percent"] == -66.6
    assert row["previous_competitor_unit"] == 4050
    assert row["competitor_unit"] == 1998
    assert row["competitor_change_unit"] == -2052
    assert row["previous_competitor_available"] is True


def test_monthly_comparison_template_prefers_persisted_comparison_rows():
    template = Path("app/templates/partials/representative_period_panel.html").read_text(
        encoding="utf-8"
    )
    assert "market_analysis.comparison_rows" in template
