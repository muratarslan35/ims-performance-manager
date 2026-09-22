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


def test_desktop_login_compacts_on_short_viewports():
    css = (ROOT / "app/static/css/auth-branding.css").read_text(encoding="utf-8")
    login = (ROOT / "app/templates/login.html").read_text(encoding="utf-8")

    assert "@media (min-width: 992px) and (max-height: 900px)" in css
    assert "body.anonymous .auth-shell-login .auth-brand-stack .auth-ims-emblem" in css
    assert "max-height: calc(100dvh - 190px);" in css
    assert "body.anonymous .auth-shell-login .portal-option span" in css
    assert "auth-branding.css', v='20260922g'" in login


def test_pc_login_and_register_use_fixed_viewport_composition():
    css = (ROOT / "app/static/css/auth-branding.css").read_text(encoding="utf-8")
    login = (ROOT / "app/templates/login.html").read_text(encoding="utf-8")
    register = (ROOT / "app/templates/register.html").read_text(encoding="utf-8")

    assert "@media (min-width: 1200px)" in css
    assert "body.anonymous .auth-shell.auth-shell-login" in css
    assert "body.anonymous .auth-shell.auth-shell-register" in css
    assert "height: 100dvh;" in css
    assert "overflow: hidden;" in css
    assert "body.anonymous .auth-shell-register .auth-layout" in css
    assert "@media (min-width: 1200px) and (max-height: 800px)" in css
    assert "auth-branding.css', v='20260922g'" in login
    assert "auth-branding.css', v='20260922g'" in register


def test_pc_auth_cards_are_centered_and_narrower():
    css = (ROOT / "app/static/css/auth-branding.css").read_text(encoding="utf-8")

    assert "/* === PC AUTH CENTERED COMPACT 20260922d === */" in css
    assert "width: min(72vw, 920px);" in css
    assert "width: min(70vw, 900px);" in css
    assert "margin-left: auto;" in css
    assert "margin-right: auto;" in css


def test_pc_auth_true_center_balance():
    css = (ROOT / "app/static/css/auth-branding.css").read_text(encoding="utf-8")

    assert "/* === PC AUTH TRUE CENTER BALANCE 20260922e === */" in css
    assert "grid-template-rows: auto auto;" in css
    assert "align-content: center;" in css
    assert "justify-items: center;" in css
    assert "width: min(66vw, 850px);" in css
    assert "height: min(430px, calc(100dvh - 210px));" in css
    assert "height: min(480px, calc(100dvh - 210px));" in css


def test_short_pc_auth_does_not_reexpand_to_viewport():
    css = (ROOT / "app/static/css/auth-branding.css").read_text(encoding="utf-8")

    assert "/* === PC AUTH SHORT VIEWPORT CORRECTION 20260922f === */" in css
    assert "height: min(388px, calc(100dvh - 270px));" in css
    assert "max-height: min(388px, calc(100dvh - 270px));" in css
    assert "height: min(438px, calc(100dvh - 270px));" in css
    assert "padding-bottom: 16px;" in css


def test_short_pc_auth_restores_balanced_scale():
    css = (ROOT / "app/static/css/auth-branding.css").read_text(encoding="utf-8")

    assert "/* === PC AUTH BALANCED SIZE 20260922g === */" in css
    assert "transform: translateY(-42px);" in css
    assert "width: min(65vw, 840px);" in css
    assert "height: 410px;" in css
    assert "height: 458px;" in css
    assert "max-height: 90px;" in css
