from pathlib import Path


def test_market_and_region_period_selectors_are_framed_buttons():
    css = Path("app/static/css/quarter-period-menu.css").read_text(encoding="utf-8")

    assert ".manager-period-toolbar-stacked" in css
    assert ".manager-period-row .manager-period-button" in css
    assert ".period-tabs.quarter-period-tabs" in css
    assert ".quarter-period-row .period-tab" in css
    assert "border:1px solid" in css
    assert "border-radius:10px" in css
    assert ".manager-period-row .manager-period-button.active" in css
    assert ".quarter-period-row .period-tab.active" in css
    assert "background:#1769c2" in css
