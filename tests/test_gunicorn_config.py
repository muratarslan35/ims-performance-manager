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


def test_heavy_ims_upload_recycles_only_the_serving_worker_after_response():
    config = _load_config()

    class Log:
        def __init__(self):
            self.messages = []

        def info(self, message):
            self.messages.append(message)

    class Worker:
        def __init__(self):
            self.alive = True
            self.log = Log()

    worker = Worker()
    config.post_request(
        worker,
        req=None,
        environ={"PATH_INFO": "/ims/upload", "REQUEST_METHOD": "POST"},
        resp=None,
    )

    assert worker.alive is False
    assert worker.log.messages


def test_normal_requests_do_not_force_worker_recycle():
    config = _load_config()

    class Log:
        def info(self, message):
            raise AssertionError("normal request should not log a forced recycle")

    class Worker:
        alive = True
        log = Log()

    worker = Worker()
    config.post_request(
        worker,
        req=None,
        environ={"PATH_INFO": "/dashboard/", "REQUEST_METHOD": "GET"},
        resp=None,
    )

    assert worker.alive is True


def test_deploy_restarts_only_after_acceptance_checks():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "deploy.yml"
    ).read_text(encoding="utf-8")

    acceptance = workflow.index("verify_ims_acceptance.py")
    service_start = workflow.index("deploy/install_systemd_service.sh")
    assert acceptance < service_start
    assert "nohup venv/bin/python run.py" not in workflow
    assert "ServerAliveInterval=30" in workflow
    assert "ServerAliveCountMax=20" in workflow


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
