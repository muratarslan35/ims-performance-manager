from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_deploy_waits_for_shared_dashboard_snapshot_acceptance():
    installer = (ROOT / "deploy/install_systemd_service.sh").read_text(encoding="utf-8")
    verifier = (ROOT / "verify_dashboard_snapshot_production.py").read_text(encoding="utf-8")

    worker_status = installer.index('sudo systemctl --no-pager --full status "$worker_service_name"')
    acceptance = installer.index('verify_dashboard_snapshot_production.py')
    assert worker_status < acceptance
    assert 'DASHBOARD_SNAPSHOT_ACTIVATION|waiting_for_active_snapshot' in installer
    assert '--wait-seconds 120' in installer
    assert '--reads 5' in installer
    assert '--max-read-seconds 2.0' in installer
    assert '[ "$release_mode" = "backend" ]' in installer
    assert '[ "$release_mode" = "import" ]' in installer
    assert '[ "$release_mode" = "heavy" ]' in installer

    assert 'DASHBOARD_SNAPSHOT_ACCEPTANCE|status=PASS' in verifier
    assert 'DASHBOARD_SNAPSHOT_ACCEPTANCE|status=FAIL|reason=not_ready' in verifier
    assert 'PersistentDashboardSnapshotService.get_active' in verifier
    assert 'PersistentDashboardSnapshotService.source_identity' in verifier
    assert 'DashboardService()' in verifier
    assert 'builder' not in verifier
    compile(verifier, 'verify_dashboard_snapshot_production.py', 'exec')


def test_every_completed_import_emits_snapshot_acceptance_after_warmup():
    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")

    warm_index = worker.index('PersistentDashboardSnapshotService.get_or_build')
    verify_index = worker.index('dashboard_snapshot_acceptance status=PASS')
    assert warm_index < verify_index
    assert 'PersistentDashboardSnapshotService.get_active(year, month)' in worker
    assert 'dashboard snapshot warm-up completed but active payload is unavailable' in worker
    assert 'completed.status == IMSImportJob.STATUS_COMPLETED' in worker
    compile(worker, 'ims_import_worker.py', 'exec')
