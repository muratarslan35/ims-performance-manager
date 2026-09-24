from pathlib import Path


def test_login_redirects_directly_to_snapshot_dashboard():
    source = Path("app/auth.py").read_text(encoding="utf-8")
    login_block = source[source.index("def login():"):source.index("def register():")]

    assert 'url_for("dashboard.index")' in login_block
    assert 'url_for("main.dashboard")' not in login_block


def test_login_does_not_show_fake_timed_full_page_progress():
    template = Path("app/templates/login.html").read_text(encoding="utf-8")

    assert 'class="auth-form" data-page-loader="false"' in template


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
