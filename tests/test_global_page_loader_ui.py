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


def test_global_page_loader_tracks_navigation_without_freezing_at_92():
    source = Path("app/static/js/layout.js").read_text(encoding="utf-8")

    assert "const elapsedTarget" in source
    assert "Math.min(99" in source
    assert "92 - current" not in source


def test_global_page_loader_does_not_touch_business_calculation_contracts():
    source = Path("app/static/js/layout.js").read_text(encoding="utf-8")

    forbidden = (
        "P2 > P1 > IMS",
        "ProductionResultService",
        "PrimeEngine",
        "realization =",
        "target_tl =",
        "unit_target =",
    )
    loader_block = source[source.index("function setupGlobalPageLoader()") : source.index("function isMobile()")]
    for token in forbidden:
        assert token not in loader_block


def test_ajax_simulation_form_does_not_start_navigation_loader():
    layout = Path("app/static/js/layout.js").read_text(encoding="utf-8")
    simulation = Path("app/templates/simulation.html").read_text(encoding="utf-8")

    assert "if (form.dataset.pageLoader === 'false') return;" in layout
    assert '<form id="simulationForm" data-page-loader="false">' in simulation
