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
    assert "_warm_representative_snapshots(app, year, month, force=True)" in worker

    # IMS/publication remains first in the single worker loop; refresh work is
    # only examined when no IMS job was claimed.
    idle = worker.index("if job is None:")
    refresh = worker.index("_process_representative_refresh_queue(app)", idle)
    process_job = worker.index("IMSImportQueue.process(job)", idle)
    assert refresh < process_job
