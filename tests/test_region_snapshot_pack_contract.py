from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_manager_region_cockpit_uses_single_snapshot_pack():
    template = (ROOT / "app/templates/market_analysis.html").read_text(encoding="utf-8")
    javascript = (ROOT / "app/static/js/manager-region-cockpit.js").read_text(encoding="utf-8")
    routes = (ROOT / "app/routes/__init__.py").read_text(encoding="utf-8")

    assert "data-region-pack-url" in template
    assert "market_analysis_regions_pack" in template
    assert "ensureRegionPack" in javascript
    assert "regionPackReady" in javascript
    assert "get_active_all" in routes
    assert 'route("/market-analysis/regions-pack")' in routes


def test_worker_backfills_existing_active_ims_without_delaying_queued_import():
    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")
    assert "_backfill_latest_region_snapshots" in worker
    assert "STATUS_QUEUED" in worker
    assert "PersistentRegionSnapshotService.build_for_period" in worker
