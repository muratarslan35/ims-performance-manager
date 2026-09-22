from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_market_region_sidebar_is_compact_only_on_desktop():
    css = (ROOT / "app/static/css/manager-region-cockpit.css").read_text(encoding="utf-8")

    assert "@media(min-width:901px)" in css
    assert ".manager-region-list{gap:1px}" in css
    assert ".manager-region-button{min-height:50px;padding:6px 9px" in css
    assert "@media(max-width:900px)" in css


def test_desktop_auth_notice_does_not_push_locked_login_viewport():
    css = (ROOT / "app/static/css/auth-branding.css").read_text(encoding="utf-8")

    assert "@media (min-width: 801px)" in css
    assert "body.auth-viewport-locked .page-body > .container-xl > .alert" in css
    assert "position: fixed;" in css
