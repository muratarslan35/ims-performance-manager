from pathlib import Path


def test_global_page_loader_is_navigation_only_and_finishes_at_window_load():
    source = Path("app/static/js/layout.js").read_text(encoding="utf-8")

    assert "function setupGlobalPageLoader()" in source
    assert "globalPageLoaderRing" in source
    assert "globalPageLoaderValue" in source
    assert "Yükleniyor" in source
    assert "Sayfa hazırlanıyor" in source
    assert "window.addEventListener('load', finish" in source
    assert "document.addEventListener('click'" in source
    assert "document.addEventListener('submit'" in source
    assert "url.origin !== window.location.origin" in source
    assert "render(Math.min(100" in source
    assert "window.IMSPageLoader" in source


def test_global_page_loader_does_not_touch_business_calculation_contracts():
    source = Path("app/static/js/layout.js").read_text(encoding="utf-8")

    forbidden = (
        "P2 > P1 > IMS",
        "ProductionResultService",
        "PrimeEngine",
        "realization =",
        "target =",
    )
    loader_block = source[source.index("function setupGlobalPageLoader()") : source.index("function isMobile()")]
    for token in forbidden:
        assert token not in loader_block
