from pathlib import Path


def test_production_refresh_queue_contract():
    queue_source = Path("app/services/representative_snapshot_refresh_queue.py").read_text(
        encoding="utf-8"
    )
    ims_source = Path("app/ims.py").read_text(encoding="utf-8")
    retry_source = Path("app/services/production_result_retry_ui.py").read_text(
        encoding="utf-8"
    )
    worker = Path("ims_import_worker.py").read_text(encoding="utf-8")

    assert "enqueue_for_production" in queue_source
    assert "status=IMSUpload.STATUS_COMPLETED" in queue_source
    assert "RepresentativeSnapshotRefreshQueue.enqueue_for_production" in ims_source
    assert "RepresentativeSnapshotRefreshQueue.enqueue_for_production" in retry_source
    assert "_process_representative_refresh_queue" in worker
    assert "dashboard_result = _warm_dashboard_snapshot(app, year, month)" in worker
    assert "region_result = _warm_region_snapshots(app, year, month)" in worker
    assert "_warm_representative_snapshots(app, year, month, force=True)" in worker
    assert "PersistentRegionSnapshotService.enrich_for_period(year, month)" in worker

    refresh_worker = worker[worker.index("def _process_representative_refresh_queue(app):") :]
    dashboard = refresh_worker.index(
        "dashboard_result = _warm_dashboard_snapshot(app, year, month)"
    )
    region = refresh_worker.index(
        "region_result = _warm_region_snapshots(app, year, month)"
    )
    representative = refresh_worker.index(
        "_warm_representative_snapshots(app, year, month, force=True)"
    )
    enrichment = refresh_worker.index(
        "PersistentRegionSnapshotService.enrich_for_period(year, month)"
    )
    completion = refresh_worker.index(
        "RepresentativeSnapshotRefreshQueue.complete(item)", enrichment
    )
    assert dashboard < region < representative < enrichment < completion
    assert 'region_result.get("status") in {"ACTIVE", "REUSED"}' in refresh_worker
    assert 'enrichment_result.get("status") in {"ENRICHED", "REUSED"}' in refresh_worker

    # IMS/publication remains first in the single worker loop; refresh work is
    # only examined when no IMS job was claimed.
    idle = worker.index("if job is None:")
    refresh = worker.index("_process_representative_refresh_queue(app)", idle)
    process_job = worker.index("IMSImportQueue.process(job)", idle)
    assert refresh < process_job
