from pathlib import Path


def test_login_redirects_directly_to_snapshot_dashboard():
    source = Path("app/auth.py").read_text(encoding="utf-8")
    login_block = source[source.index("def login():"):source.index("def register():")]

    assert 'url_for("dashboard.index")' in login_block
    assert 'url_for("main.dashboard")' not in login_block


def test_login_keeps_page_loader_for_real_navigation_lifecycle():
    template = Path("app/templates/login.html").read_text(encoding="utf-8")

    assert 'class="auth-form"' in template
    assert 'class="auth-form" data-page-loader="false"' not in template


def test_page_loader_uses_document_milestones_not_elapsed_fake_progress():
    source = Path("app/static/js/layout.js").read_text(encoding="utf-8")

    assert "ims-page-navigation-active" in source
    assert "beforeunload" in source
    assert "sessionStorage.getItem(navigationKey)" in source
    assert "window.addEventListener('load'" in source
    assert "Math.exp(-elapsed" not in source


def test_dashboard_snapshot_decode_is_generation_cached():
    source = Path(
        "app/services/persistent_dashboard_snapshot_service.py"
    ).read_text(encoding="utf-8")

    assert "@lru_cache(maxsize=12)" in source
    assert "stat.st_mtime_ns" in source
    assert "stat.st_size" in source
    get_active = source[source.index("def get_active("):source.index("def get_generation_for_upload(")]
    assert "cls._read_envelope(path)" in get_active
    assert "cls._read_envelope(stable_path)" in get_active
