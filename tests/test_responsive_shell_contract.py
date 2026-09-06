from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_responsive_shell_contract_is_loaded_after_page_styles():
    base = (ROOT / "app/templates/base.html").read_text(encoding="utf-8")
    marker = "css/responsive-shell-contract.css"
    assert marker in base
    assert base.index("{% block styles %}") < base.index(marker)


def test_three_view_breakpoints_and_mobile_market_width_contract_exist():
    css = (ROOT / "app/static/css/responsive-shell-contract.css").read_text(encoding="utf-8")
    assert "@media (min-width:1200px)" in css
    assert "@media (min-width:768px) and (max-width:1199.98px)" in css
    assert "@media (max-width:767.98px)" in css
    assert ".manager-region-cockpit" in css
    assert ".exec-cockpit" in css
    assert "grid-template-columns:1fr!important" in css
    assert "overflow-x:auto" in css


def test_global_page_loader_is_forced_to_visual_viewport_center():
    css = (ROOT / "app/static/css/responsive-shell-contract.css").read_text(encoding="utf-8")
    assert "#globalPageLoader{" in css
    assert "width:100vw!important" in css
    assert "height:100dvh!important" in css
    assert "left:50vw!important" in css
    assert "top:50dvh!important" in css
    assert "transform:translate(-50%,-50%)!important" in css


def test_responsive_contract_does_not_reference_business_calculation_services():
    css = (ROOT / "app/static/css/responsive-shell-contract.css").read_text(encoding="utf-8")
    forbidden = ("ProductionResultService", "PrimeEngine", "P2 > P1 > IMS", "realization =", "target =")
    for token in forbidden:
        assert token not in css
