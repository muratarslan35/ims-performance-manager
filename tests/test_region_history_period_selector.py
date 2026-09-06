from pathlib import Path


def test_region_history_selector_is_global_and_market_period_is_static():
    template = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "templates"
        / "region_performance.html"
    ).read_text(encoding="utf-8")

    assert 'id="region-history-period"' in template
    assert "GEÇMİŞ AYLAR" in template
    assert "market_analysis.available_periods" in template
    assert "window.location.href=this.value" in template
    assert "market-period-select" not in template
    assert "market-period-label" in template
    assert "ANALİZ DÖNEMİ" in template
    assert "month_names[report.month - 1]" in template


def test_history_selector_is_in_region_header_not_market_header():
    template = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "templates"
        / "region_performance.html"
    ).read_text(encoding="utf-8")

    selector = template.index('id="region-history-period"')
    market = template.index('class="region-market"')
    assert selector < market
