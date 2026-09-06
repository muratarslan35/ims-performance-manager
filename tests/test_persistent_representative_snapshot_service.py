from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_representative_route_prefers_durable_snapshot_before_live_builder():
    source = (ROOT / "app/services/representative_period_workspace.py").read_text(encoding="utf-8")
    lookup = source.index("PersistentRepresentativeSnapshotService.get_active(")
    fallback = source.index("build_representative_workspace_payload(representative, year, month)", lookup)
    assert lookup < fallback
    assert 'workspace["snapshots"]' in source
    assert 'workspace["annual_realization"]' in source


def test_snapshot_builder_reuses_existing_calculation_path_without_formula_changes():
    source = (ROOT / "app/services/representative_period_workspace.py").read_text(encoding="utf-8")
    assert "def build_representative_workspace_payload" in source
    assert "ProductionResultService.effective_products" in source
    assert "CompetitiveIntelligenceService(" in source
    assert "AnnualRealizationService.build" in source
    assert "ScopedAIInsightService.build" in source
    assert "for key, label, _kind in PERIOD_OPTIONS" in source


def test_persistent_generation_is_atomic_and_keeps_previous_active_during_build():
    source = (ROOT / "app/services/persistent_representative_snapshot_service.py").read_text(encoding="utf-8")
    assert 'STATUS_BUILDING = "BUILDING"' in source
    assert 'STATUS_ACTIVE = "ACTIVE"' in source
    assert 'STATUS_SUPERSEDED = "SUPERSEDED"' in source
    assert 'STATUS_FAILED = "FAILED"' in source
    assert "_visible_set_id" in source
    assert "_current_source_building" in source
    assert "previous = db.session.execute" in source
    assert "status=cls.STATUS_ACTIVE" in source


def test_background_worker_warms_representatives_without_first_user_request():
    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")
    assert "def _warm_representative_snapshots" in worker
    assert "PersistentRepresentativeSnapshotService.build_for_period" in worker
    assert "_warm_representative_snapshots(app, job_year, job_month)" in worker
    assert "_warm_representative_snapshots(app, latest.year, latest.month)" in worker


def test_deploy_bootstraps_first_active_generation_before_web_activation():
    installer = (ROOT / "deploy/install_systemd_service.sh").read_text(encoding="utf-8")
    bootstrap = installer.index("REPRESENTATIVE_SNAPSHOT_BOOTSTRAP|ensure_active_before_web")
    web_activation = installer.index('if sudo systemctl is-active --quiet "$service_name"')
    assert bootstrap < web_activation
    assert 'backfill_active_representative_snapshots.py"\n' in installer


def test_backend_deploy_starts_nonblocking_representative_snapshot_refresh():
    installer = (ROOT / "deploy/install_systemd_service.sh").read_text(encoding="utf-8")
    assert "REPRESENTATIVE_SNAPSHOT_ACTIVATION|background_force_rebuild" in installer
    assert "backfill_active_representative_snapshots.py\" --force" in installer
    assert "nohup env PYTHONPATH=" in installer
    assert "representative_snapshot_warmup.log" in installer


def test_snapshot_migration_adds_only_derived_cache_tables():
    migration = (ROOT / "migrations/versions/a2b3c4d5e6f7_add_representative_snapshots.py").read_text(encoding="utf-8")
    assert 'down_revision = ("z0n1p2q3r4s5", "b2q3s4j5d6e7")' in migration
    assert '"representative_snapshot_sets"' in migration
    assert '"representative_snapshots"' in migration
    assert "targets" not in migration
    assert "ims_raw_data" not in migration
    assert "production_results" not in migration
