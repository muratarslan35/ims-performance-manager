from pathlib import Path


def test_deploy_workflow_is_change_aware_and_keeps_heavy_gates_bounded():
    text = Path('.github/workflows/deploy.yml').read_text(encoding='utf-8')

    assert 'Classify release change' in text
    assert 'RELEASE_CLASS|mode=' in text
    assert "mode=\"heavy\"" in text
    assert "mode=\"backend\"" in text
    assert "mode=\"ui\"" in text
    assert "mode=\"docs\"" in text

    assert "if [ \"$RELEASE_MODE\" = \"heavy\" ]; then" in text
    heavy_index = text.index("if [ \"$RELEASE_MODE\" = \"heavy\" ]; then")
    acceptance_index = text.index('venv/bin/python verify_ims_acceptance.py')
    service_index = text.index('deploy/install_systemd_service.sh')
    assert heavy_index < acceptance_index < service_index
    assert 'timeout --signal=TERM --kill-after=30s 900s' in text
    assert 'sqlite_online_backup.py instance/ipm.db "$acceptance_db"' in text

    assert 'FAST BACKEND RELEASE GATES' in text
    assert 'FAST UI RELEASE: DB/IMS GATES SKIPPED' in text
    assert 'Production health check passed.' in text


def test_heavy_benchmark_is_not_automatic_after_deploy():
    benchmark = Path('.github/workflows/ims-server-benchmark.yml').read_text(encoding='utf-8')
    assert 'workflow_dispatch:' in benchmark
    assert 'workflow_run:' not in benchmark
