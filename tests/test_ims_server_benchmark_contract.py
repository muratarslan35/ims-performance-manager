from pathlib import Path


def test_server_benchmark_is_fail_closed_and_never_targets_live_db():
    text = Path("benchmark_ims_import.py").read_text(encoding="utf-8")
    assert "ims-benchmark-" in text
    assert "Canlı DB üzerinde benchmark engellendi" in text
    assert "clear_before_import=False" in text
    assert "reconciliation_status" in text
    assert "counts[\"fact\"] <= 0" in text
    assert "BLOCKING_STATS" in text


def test_server_benchmark_workflow_uses_isolated_online_backup_after_successful_deploy():
    text = Path(".github/workflows/ims-server-benchmark.yml").read_text(encoding="utf-8")
    assert "workflow_run:" in text
    assert "github.event.workflow_run.conclusion == 'success'" in text
    assert 'benchmark_db="/tmp/ims-benchmark-${stamp}.db"' in text
    assert 'sqlite_online_backup.py instance/ipm.db "$benchmark_db"' in text
    assert 'DATABASE_URL="sqlite:///$benchmark_db"' in text
    assert "benchmark_ims_import.py" in text
    assert "IMS_SERVER_BENCHMARK_LIVE_DB" in text
    assert "systemctl restart" not in text
    assert "install_systemd_service" not in text
