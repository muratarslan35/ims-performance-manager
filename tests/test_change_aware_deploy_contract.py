from pathlib import Path


def test_deploy_workflow_is_change_aware_and_keeps_expensive_gates_bounded():
    text = Path('.github/workflows/deploy.yml').read_text(encoding='utf-8')

    assert 'Classify release change' in text
    assert 'RELEASE_CLASS|mode=' in text
    assert 'mode="import"' in text
    assert 'mode="heavy"' in text
    assert 'mode="backend"' in text
    assert 'mode="ui"' in text
    assert 'mode="docs"' in text

    # Import changes retain full regression coverage while the 50-upload probe
    # runs in a separate job, so safety is preserved without serial wall time.
    assert 'Import full suite' in text
    assert 'PR 50-upload scale probe' in text
    assert 'Run bounded 50-upload scale probe' in text

    heavy_marker = '--- HEAVY DB/MIGRATION RELEASE GATES ---'
    import_marker = '--- FAST IMPORT RELEASE GATES ---'
    backend_marker = '--- FAST BACKEND RELEASE GATES ---'
    heavy_index = text.index(heavy_marker)
    import_index = text.index(import_marker)
    backend_index = text.index(backend_marker)
    service_index = text.index('deploy/install_systemd_service.sh')
    assert heavy_index < import_index < backend_index < service_index

    heavy_block = text[heavy_index:import_index]
    import_block = text[import_index:backend_index]

    assert 'sqlite_online_backup.py' in heavy_block
    assert 'database_capacity_audit.py' in heavy_block
    assert '--optimize' not in heavy_block
    assert 'verify_live_ims_gate.py' in heavy_block

    assert 'verify_runtime.py' in import_block
    assert 'sqlite_fast_check' in import_block
    assert 'verify_live_ims_gate.py' in import_block
    assert 'production_resource_gate.py' in import_block
    assert 'sqlite_online_backup.py' not in import_block
    assert 'database_capacity_audit.py' not in import_block
    assert 'cleanup_old_backups.py' not in import_block

    assert 'IMS_WORKER_IDLE|processing=' in text
    assert 'Active IMS import detected; deploy refused' in text
    assert 'PRAGMA quick_check(1)' in text
    assert 'Production health check passed.' in text
    assert 'IMS worker health check passed.' in text

    # Real-workbook acceptance remains manual qualification rather than an
    # automatic production re-import.
    assert 'venv/bin/python verify_ims_acceptance.py' not in text
    assert 'sqlite_online_backup.py instance/ipm.db "$acceptance_db"' not in text


def test_service_activation_uses_reload_for_code_only_releases():
    text = Path('deploy/install_systemd_service.sh').read_text(encoding='utf-8')

    assert 'release_mode=${2:-heavy}' in text
    assert 'sudo systemctl reload "$service_name"' in text
    assert 'if [ "$release_mode" = "heavy" ]; then' in text
    assert 'if [ "$release_mode" = "import" ] || [ "$release_mode" = "heavy" ]; then' in text
    assert 'SERVICE_ACTIVATION|worker=preserved' in text


def test_expensive_capacity_and_backup_retention_are_weekly_maintenance():
    deploy = Path('.github/workflows/deploy.yml').read_text(encoding='utf-8')
    maintenance = Path('.github/workflows/ims-production-maintenance.yml').read_text(encoding='utf-8')

    assert 'cleanup_old_backups.py' not in deploy
    assert 'schedule:' in maintenance
    assert 'database_capacity_audit.py --database instance/ipm.db --additional-uploads 49 --optimize' in maintenance
    assert 'cleanup_old_backups.py' in maintenance
    assert 'MAINTENANCE_SKIPPED|reason=active_import' in maintenance
    assert 'MAINTENANCE_RESULT|PASS' in maintenance
    assert 'install_systemd_service.sh' not in maintenance


def test_heavy_benchmark_is_not_automatic_after_deploy():
    benchmark = Path('.github/workflows/ims-server-benchmark.yml').read_text(encoding='utf-8')
    assert 'workflow_dispatch:' in benchmark
    assert 'workflow_run:' not in benchmark
