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
    assert "dependency_periods" in queue_source
    assert "enqueue_stale_production_dependencies" in queue_source
    assert "ProductionResultUpload.STATUS_APPLIED" in queue_source
    assert "requested_at" in queue_source
    assert "RepresentativeSnapshotRefreshQueue.enqueue_for_production" in ims_source
    assert "RepresentativeSnapshotRefreshQueue.enqueue_for_production" in retry_source
    assert "_process_representative_refresh_queue" in worker
    assert "dashboard_result = _warm_dashboard_snapshot(app, year, month, force=True)" in worker
    assert "region_result = _warm_region_snapshots(app, year, month, force=True)" in worker
    assert "_warm_representative_snapshots(" in worker
    assert "app, year, month, force=True" in worker
    assert "PersistentRegionSnapshotService.enrich_for_period(year, month)" in worker
    assert "enqueue_stale_production_dependencies" in worker

    refresh_worker = worker[worker.index("def _process_representative_refresh_queue(app):") :]
    dashboard = refresh_worker.index(
        "dashboard_result = _warm_dashboard_snapshot(app, year, month, force=True)"
    )
    representative = refresh_worker.index(
        "representative_result = _warm_representative_snapshots("
    )
    region = refresh_worker.index(
        "region_result = _warm_region_snapshots(app, year, month, force=True)"
    )
    enrichment = refresh_worker.index(
        "PersistentRegionSnapshotService.enrich_for_period(year, month)"
    )
    completion = refresh_worker.index(
        "RepresentativeSnapshotRefreshQueue.complete(item)", enrichment
    )
    assert dashboard < representative < region < enrichment < completion
    assert 'region_result.get("status") in {"ACTIVE", "REUSED"}' in refresh_worker
    assert 'enrichment_result.get("status") in {"ENRICHED", "REUSED"}' in refresh_worker

    # IMS/publication remains first in the single worker loop; refresh work is
    # only examined when no IMS job was claimed.
    idle = worker.index("if job is None:")
    reconcile = worker.index("enqueue_stale_production_dependencies", idle)
    refresh = worker.index("_process_representative_refresh_queue(app)", idle)
    process_job = worker.index("IMSImportQueue.process(job)", idle)
    assert reconcile < refresh < process_job


def test_late_production_cascade_contract():
    queue_source = Path("app/services/representative_snapshot_refresh_queue.py").read_text(
        encoding="utf-8"
    )
    region_source = Path("app/services/persistent_region_snapshot_service.py").read_text(
        encoding="utf-8"
    )
    worker = Path("ims_import_worker.py").read_text(encoding="utf-8")

    # Same-year completed IMS periods at/after the finalized month are dependent.
    assert "int(row[0]) == year" in queue_source
    assert "int(row[1]) >= month" in queue_source
    # December production also changes the following January comparison.
    assert "month == 12" in queue_source
    assert "int(row[0]) == year + 1" in queue_source
    assert "int(row[1]) == 1" in queue_source

    # Downstream periods cannot be treated as REUSED merely because their own
    # IMS/production identity is unchanged.
    assert "force: bool = False" in region_source
    assert "existing_complete and not force" in region_source
    assert "existing_complete and force" in region_source
    assert "replacement_rows" in region_source
    assert "PersistentDashboardSnapshotService.publish(year, month, _payload)" in worker
