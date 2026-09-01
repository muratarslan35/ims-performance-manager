from pathlib import Path


def test_deploy_workflow_is_change_aware_and_keeps_expensive_gates_bounded():
    text = Path('.github/workflows/deploy.yml').read_text(encoding='utf-8')

    assert 'Classify release change' in text
    assert 'RELEASE_CLASS|mode=' in text
    assert 'mode="import"' in text
    assert 'mode="heavy"' in text
    assert 'mode="backend"' in text
    assert 'mode="ui"' in text
    assert 'mode="ops"' in text
    assert 'mode="docs"' in text

    # Import changes retain full regression coverage while the 50-upload probe
    # runs in a separate job, so safety is preserved without serial wall time.
    assert 'Import full suite' in text
    assert 'PR 50-upload scale probe' in text
    assert 'Run bounded 50-upload scale probe' in text

    heavy_marker = '--- HEAVY DB/MIGRATION RELEASE GATES ---'
    import_marker = '--- FAST IMPORT RELEASE GATES ---'
    backend_marker = '--- FAST BACKEND RELEASE GATES ---'
    ops_marker = '--- OPS RELEASE: SYNC + ACCEPTANCE, NO SERVICE ACTIVATION ---'
    heavy_index = text.index(heavy_marker)
    import_index = text.index(import_marker)
    backend_index = text.index(backend_marker)
    ops_index = text.index(ops_marker)
    service_index = text.index('deploy/install_systemd_service.sh')
    assert heavy_index < import_index < backend_index < ops_index < service_index

    heavy_block = text[heavy_index:import_index]
    import_block = text[import_index:backend_index]
    backend_block = text[backend_index:ops_index]
    ops_block = text[ops_index:service_index]

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

    # Backend-only code releases do not mutate the database. They must keep the
    # immediate WAL/busy_timeout gate but avoid a multi-minute full quick_check.
    assert 'verify_runtime.py' in backend_block
    assert 'sqlite_runtime_check' in backend_block
    assert 'sqlite_fast_check' not in backend_block

    # DB/import/ops paths retain the full SQLite quick_check acceptance gate.
    assert 'verify_runtime.py' in ops_block
    assert 'sqlite_fast_check' in ops_block
    assert 'sqlite_online_backup.py' not in ops_block
    assert 'database_capacity_audit.py' not in ops_block

    assert 'IMS_WORKER_IDLE|processing=' in text
    assert 'Active IMS import detected; deploy refused' in text
    assert 'PRAGMA quick_check(1)' in text
    assert 'SQLITE_RUNTIME|' in text
    assert 'quick_check=skipped_backend_no_db_change' in text
    assert 'Production health check passed.' in text
    assert 'IMS worker health check passed.' in text
    assert 'HTTP_HEALTH|PASS' in text
    assert 'WEB_ACTIVE|' in text
    assert 'WORKER_ACTIVE|' in text
    assert 'venv/bin/python verify_region_manager_production.py' in text
    assert 'REGION_MANAGER_ACCEPTANCE\\|' in text
    assert '|| [ "$RELEASE_MODE" = "backend" ]' in text
    acceptance = Path('verify_region_manager_production.py').read_text(encoding='utf-8')
    assert 'session["portal"] = "manager"' in acceptance
    compile(acceptance, 'verify_region_manager_production.py', 'exec')

    # Real-workbook acceptance remains manual qualification rather than an
    # automatic production re-import.
    assert 'venv/bin/python verify_ims_acceptance.py' not in text
    assert 'sqlite_online_backup.py instance/ipm.db "$acceptance_db"' not in text


def test_ops_release_avoids_heavy_db_work_and_service_activation():
    text = Path('.github/workflows/deploy.yml').read_text(encoding='utf-8')

    assert '.github/workflows/ims-production-maintenance.yml|scripts/run_production_maintenance.sh|tests/*' in text
    assert 'if [ "$mode" = "docs" ]; then mode="ops"; fi' in text
    assert 'Ops full suite' in text
    assert 'Ops smoke' in text
    assert 'timeout-minutes: 35' in text
    assert 'SERVICE_ACTIVATION|skipped=ops' in text
    assert 'if [ "$RELEASE_MODE" = "ops" ]; then' in text
    assert 'ServerAliveInterval=15' in text
    assert 'ServerAliveCountMax=40' in text
    assert 'ConnectionAttempts=3' in text


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
    runner = Path('scripts/run_production_maintenance.sh').read_text(encoding='utf-8')

    # The filename can legitimately appear in the classifier, but the deploy
    # execution path itself must never run backup retention synchronously.
    execution_start = deploy.index('--- HEAVY DB/MIGRATION RELEASE GATES ---')
    execution_end = deploy.index('- name: Publish compact deployment evidence')
    deploy_execution = deploy[execution_start:execution_end]
    assert 'cleanup_old_backups.py' not in deploy_execution

    assert 'schedule:' in maintenance
    assert 'Launch detached maintenance job' in maintenance
    assert 'Poll detached maintenance job' in maintenance
    assert 'Collect final maintenance evidence' in maintenance
    assert 'nohup bash scripts/run_production_maintenance.sh' in maintenance
    assert 'ConnectionAttempts=3' in maintenance
    assert 'SSH_POLL_RETRY|' in maintenance
    assert 'consecutive_ssh_failures' in maintenance
    assert 'install_systemd_service.sh' not in maintenance

    assert 'database_capacity_audit.py' in runner
    assert '--additional-uploads 49' in runner
    assert '--optimize' in runner
    assert 'cleanup_old_backups.py' in runner
    assert '--keep-latest 2' in runner
    assert 'MAINTENANCE_SKIPPED|reason=active_import' in runner
    assert 'IMS_PROCESSING|' in runner
    assert 'SQLITE_JOURNAL_MODE|' in runner
    assert 'SQLITE_BUSY_TIMEOUT|' in runner
    assert 'SQLITE_QUICK_CHECK|' in runner
    assert 'WEB_ACTIVE|' in runner
    assert 'WORKER_ACTIVE|' in runner
    assert 'HTTP_HEALTH|PASS' in runner
    assert 'MAINTENANCE_RESULT|PASS' in runner


def test_detached_maintenance_status_survives_runner_disconnect():
    maintenance = Path('.github/workflows/ims-production-maintenance.yml').read_text(encoding='utf-8')
    runner = Path('scripts/run_production_maintenance.sh').read_text(encoding='utf-8')

    # Long-running work is owned by the production host, not by one SSH session.
    assert '>"$JOB_DIR/nohup.log" 2>&1 </dev/null &' in maintenance
    assert "printf 'RUNNING\\n' > \"$STATUS_FILE\"" in runner
    assert "printf 'PASS\\n' > \"$STATUS_FILE\"" in runner
    assert "printf 'FAIL|exit_code=%s\\n'" in runner
    assert 'flock -n 9' in runner

    # GitHub Actions performs only bounded status probes and tolerates transient
    # SSH failures before declaring connectivity lost.
    assert 'for poll in $(seq 1 120)' in maintenance
    assert 'sleep 10' in maintenance
    assert '"$consecutive_ssh_failures" -ge 6' in maintenance

    # A runner/network failure must not delete state for a detached job that is
    # still RUNNING; cleanup is only allowed after a terminal status.
    assert 'REMOTE_JOB_PRESERVED|status=' in maintenance
    assert 'PASS|FAIL*) rm -rf' in maintenance


def test_heavy_benchmark_is_not_automatic_after_deploy():
    benchmark = Path('.github/workflows/ims-server-benchmark.yml').read_text(encoding='utf-8')
    assert 'workflow_dispatch:' in benchmark
    assert 'workflow_run:' not in benchmark
