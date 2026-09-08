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
