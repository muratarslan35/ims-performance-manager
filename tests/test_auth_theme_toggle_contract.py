from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_login_and_register_expose_prelogin_theme_control_only_through_shared_partial():
    login = (ROOT / "app/templates/login.html").read_text(encoding="utf-8")
    register = (ROOT / "app/templates/register.html").read_text(encoding="utf-8")
    partial = (ROOT / "app/templates/partials/auth_theme_toggle.html").read_text(encoding="utf-8")
    for template in (login, register):
        assert '{% include "partials/auth_theme_toggle.html" %}' in template
    assert "data-auth-theme-toggle" in partial
    assert "data-auth-theme-icon" in partial
    assert "themeToggleBtn" not in partial


def test_prelogin_theme_uses_existing_persisted_theme_engine_and_top_right_auth_css():
    layout = (ROOT / "app/static/js/layout.js").read_text(encoding="utf-8")
    css = (ROOT / "app/static/css/auth-branding.css").read_text(encoding="utf-8")
    assert "const THEME_KEY = 'ims-theme'" in layout
    assert "authThemeBtns" in layout
    assert "localStorage.setItem(THEME_KEY, next)" in layout
    assert "data-auth-theme-icon" in layout
    assert "/* Pre-login theme toggle */" in css
    assert "position: fixed" in css
    assert "right: max(16px, env(safe-area-inset-right))" in css
    assert '[data-theme="dark"] .auth-theme-toggle' in css
