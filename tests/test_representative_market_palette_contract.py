from pathlib import Path


def test_market_product_table_uses_page_palette_without_row_wide_status_colors():
    css = Path("app/static/css/representative-period-workspace.css").read_text(encoding="utf-8")

    assert ".market-product-table .attention-row" in css
    assert "color:var(--tblr-body-color" in css
    assert ".market-product-table .attention-strong .market-share-pill" in css
    assert ".market-product-table .attention-warning .market-share-pill" in css
    assert ".market-product-table .attention-critical .market-share-pill" in css
    assert ".market-product-table .attention-strong .attention-badge" in css
    assert ".market-product-table .attention-critical .attention-badge" in css
    assert "[data-theme=dark] .market-product-table .attention-row" in css
