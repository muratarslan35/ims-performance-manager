from pathlib import Path



ROOT = Path(__file__).resolve().parents[1]


def test_import_progress_reserves_time_for_representative_snapshots():
    queue = (ROOT / "app/services/ims_import_queue.py").read_text(encoding="utf-8")
    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")
    assert '"commit_upload": (39, 40' in queue
    assert "value = 42 + round(52 * done / max(total, 1))" in worker
    assert "recent_seconds = deque(maxlen=12)" in worker


def test_representative_roster_comes_from_exact_ims_upload():
    source = (ROOT / "app/services/persistent_representative_snapshot_service.py").read_text(encoding="utf-8")
    assert "IMSRawData.upload_id == upload_id" in source
    assert "Target.year == int(year)" not in source
    assert "if index % 8 == 0 or index == total" in source


def test_publication_is_atomic_and_notice_is_per_user():
    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")
    service = (ROOT / "app/services/ims_publication_service.py").read_text(encoding="utf-8")
    layout = (ROOT / "app/static/js/layout.js").read_text(encoding="utf-8")
    publish = worker[worker.index("def _prepare_and_publish"):]
    assert publish.index("_warm_representative_snapshots(") < publish.index("dashboard_result = _warm_dashboard_snapshot")
    assert 'summary["publication_ready"] = True' in worker
    assert 'stage="snapshot_retry"' in worker
    assert '"ims_publication_receipts"' in service
    assert "upload = cls.latest_visible_upload()" in service
    assert '"commit_upload", "final_checks", "read_models"' in service
    assert 'pending_progress.get("stage") in committed_unlinked_stages' in service
    assert "checkPublishedIMSNotice();" in layout
    assert "ims-published-notice-layer" in layout
    assert "Yeni IMS başarıyla yüklendi" in layout
    assert "aria-modal" in layout
