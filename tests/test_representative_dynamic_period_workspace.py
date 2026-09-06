from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_representative_period_switch_is_client_side_and_ai_is_last():
    template = (ROOT / "app" / "templates" / "representative_detail.html").read_text(encoding="utf-8")
    partial = (ROOT / "app" / "templates" / "partials" / "representative_period_panel.html").read_text(encoding="utf-8")

    assert 'data-rep-period="{{ key }}"' in template
    assert 'href="/representatives/view/' not in template
    assert 'data-rep-period-panel="{{ key }}"' in template
    assert "window.history.replaceState" in template
    assert "window.location.assign(`/representatives/view/${selector.value}" in template
    assert partial.index('class="representative-market-section') < partial.index('class="rep-ai-bottom')
    assert partial.count('include "partials/scoped_ai_panel.html"') == 1


def test_representative_period_service_preloads_all_periods_with_request_local_caches():
    service = (ROOT / "app" / "services" / "representative_period_workspace.py").read_text(encoding="utf-8")

    assert "sales_cache = {}" in service
    assert "assignment_cache = {}" in service
    assert "market_cache = {}" in service
    assert "for key, label, _kind in PERIOD_OPTIONS:" in service
    assert '"period_snapshots":' not in service  # template context is passed as a keyword, not serialized client-side
    assert "period_snapshots=snapshots" in service


def test_market_product_table_is_neutral_and_dark_mode_uses_surface_tokens():
    css = (ROOT / "app" / "static" / "css" / "representative_detail.css").read_text(encoding="utf-8")

    assert ".market-product-table .attention-row.attention-critical" in css
    assert "border-left-color:transparent!important" in css
    assert "[data-bs-theme=dark] .representative-market-section" in css
    assert "var(--tblr-bg-surface" in css
