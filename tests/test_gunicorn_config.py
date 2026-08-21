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


def test_deploy_restarts_only_after_acceptance_checks():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "deploy.yml"
    ).read_text(encoding="utf-8")

    acceptance = workflow.index("verify_ims_acceptance.py")
    service_start = workflow.index("deploy/install_systemd_service.sh")
    assert acceptance < service_start
    assert "nohup venv/bin/python run.py" not in workflow
