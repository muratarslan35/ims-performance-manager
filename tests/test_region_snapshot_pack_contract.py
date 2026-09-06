from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_manager_region_cockpit_uses_preloaded_snapshot_pack():
    template = (ROOT / "app/templates/market_analysis.html").read_text(encoding="utf-8")
    javascript = (ROOT / "app/static/js/manager-region-cockpit.js").read_text(encoding="utf-8")
    routes = (ROOT / "app/routes/__init__.py").read_text(encoding="utf-8")

    assert "data-manager-region-preloaded" in template
    assert "embedded_region_html" in template
    assert "hydrateEmbeddedRegions" in javascript
    assert "markPackReadyIfComplete" in javascript
    assert "get_active_all" in routes
    assert "embedded_region_html" in routes
    assert 'route("/market-analysis/regions-pack")' in routes


def test_single_pack_endpoint_remains_safe_fallback():
    template = (ROOT / "app/templates/market_analysis.html").read_text(encoding="utf-8")
    javascript = (ROOT / "app/static/js/manager-region-cockpit.js").read_text(encoding="utf-8")

    assert "data-region-pack-url" in template
    assert "market_analysis_regions_pack" in template
    assert "ensureRegionPack" in javascript
    assert "regionPackReady" in javascript
    assert "fetchRegionHtml" in javascript
    assert "prefetchRegion" in javascript


def test_worker_backfills_existing_active_ims_without_delaying_queued_import():
    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")
    assert "_backfill_latest_region_snapshots" in worker
    assert "STATUS_QUEUED" in worker
    assert "PersistentRegionSnapshotService.build_for_period" in worker


def test_runtime_deploy_refreshes_snapshot_before_web_activation():
    installer = (ROOT / "deploy/install_systemd_service.sh").read_text(encoding="utf-8")
    backfill_pos = installer.index("scripts/backfill_active_region_snapshots.py")
    web_activation_pos = installer.index("if sudo systemctl is-active --quiet \"$service_name\"")
    assert backfill_pos < web_activation_pos
    assert 'REGION_SNAPSHOT_ACTIVATION|building_latest_before_web_activation' in installer
    assert 'REGION_SNAPSHOT_ACTIVATION|force_rebuild_after_backend_change' in installer
    assert 'backfill_active_region_snapshots.py\" --force' in installer
    assert '[ "$release_mode" = "backend" ] || [ "$release_mode" = "heavy" ]' in installer


def test_force_backfill_invalidates_only_snapshot_cache_not_business_data():
    script = (ROOT / "scripts/backfill_active_region_snapshots.py").read_text(encoding="utf-8")
    assert 'parser.add_argument(' in script
    assert '"--force"' in script
    assert "region_snapshots.delete()" in script
    assert "region_snapshot_sets.delete()" in script
    assert "Target" not in script
    assert "IMSFact" not in script
    assert "IMSSummary" not in script
