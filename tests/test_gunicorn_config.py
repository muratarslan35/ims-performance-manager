import importlib.util
from pathlib import Path


def _load_config():
    path = Path(__file__).resolve().parents[1] / "gunicorn.conf.py"
    spec = importlib.util.spec_from_file_location("ims_gunicorn_config", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_worker_recommendation_is_bounded_for_small_and_large_hosts():
    config = _load_config()

    assert config.recommended_workers(cpu_count=1, memory_mb=1024) == 2
    assert config.recommended_workers(cpu_count=8, memory_mb=2048) == 2
    assert config.recommended_workers(cpu_count=8, memory_mb=4096) == 3
    assert config.recommended_workers(cpu_count=32, memory_mb=16384) == 4


def test_runtime_uses_threaded_workers_without_preloading_sqlite_state():
    config = _load_config()

    assert config.worker_class == "gthread"
    assert config.threads >= 2
    assert config.timeout >= 600
    assert config.preload_app is False
    assert 2 <= config.workers <= 4


def test_ims_upload_response_is_not_force_recycled_in_post_request():
    config = _load_config()

    assert not hasattr(config, "post_request")
    source = (Path(__file__).resolve().parents[1] / "gunicorn.conf.py").read_text(encoding="utf-8")
    assert "worker.alive = False" not in source


def test_periodic_worker_recycling_remains_enabled():
    config = _load_config()

    assert config.max_requests > 0
    assert config.max_requests_jitter >= 0


def test_heavy_deploy_restarts_only_after_isolated_acceptance():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "deploy.yml"
    ).read_text(encoding="utf-8")

    acceptance = workflow.index("venv/bin/python verify_ims_acceptance.py")
    service_start = workflow.index("deploy/install_systemd_service.sh")
    heavy_gate = workflow.index('if [ "$RELEASE_MODE" = "heavy" ]; then')
    assert heavy_gate < acceptance < service_start
    assert "nohup venv/bin/python run.py" not in workflow
    assert "ServerAliveInterval=30" in workflow
    assert "ServerAliveCountMax=20" in workflow
    assert "timeout --signal=TERM --kill-after=30s 900s" in workflow
    assert 'sqlite_online_backup.py instance/ipm.db "$acceptance_db"' in workflow
    assert "FAST BACKEND RELEASE GATES" in workflow
    assert "FAST UI RELEASE: DB/IMS GATES SKIPPED" in workflow
    assert "Production health check passed." in workflow


def test_managed_service_requires_persistent_secret_environment():
    root = Path(__file__).resolve().parents[1]
    service = (root / "deploy" / "ims-performance-manager.service.in").read_text(
        encoding="utf-8"
    )
    installer = (root / "deploy" / "install_systemd_service.sh").read_text(
        encoding="utf-8"
    )

    assert "Environment=APP_ENV=production" in service
    assert "EnvironmentFile=-/etc/ims-performance-manager.env" in service
    assert "instance/.secret_key" in installer
    assert "install -o root -g root -m 0600" in installer


def test_import_worker_is_a_separate_bounded_systemd_service():
    root = Path(__file__).resolve().parents[1]
    worker = (root / "deploy" / "ims-import-worker.service.in").read_text(encoding="utf-8")
    installer = (root / "deploy" / "install_systemd_service.sh").read_text(encoding="utf-8")
    assert "ims_import_worker.py" in worker
    assert "MemoryHigh=" in worker and "MemoryMax=" in worker
    assert "Nice=10" in worker
    assert "ims-import-worker.service" in installer
    assert 'systemctl enable "$worker_service_name"' in installer
    assert 'systemctl --no-pager --full status "$worker_service_name"' in installer
