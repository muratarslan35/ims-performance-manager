from pathlib import Path



ROOT = Path(__file__).resolve().parents[1]


def test_import_progress_reserves_time_for_representative_snapshots():
    queue = (ROOT / "app/services/ims_import_queue.py").read_text(encoding="utf-8")
    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")
    assert '"commit_upload": (39, 40' in queue
    assert "value = 46 + round(48 * done / max(total, 1))" in worker
    assert "recent_seconds = deque(maxlen=12)" in worker


def test_representative_roster_comes_from_exact_ims_upload():
    source = (ROOT / "app/services/persistent_representative_snapshot_service.py").read_text(encoding="utf-8")
    assert "IMSRawData.upload_id == upload_id" in source
    assert "Target.year == int(year)" not in source
    assert "for offset in range(0, len(build_ids), batch_size)" in source
    assert "db.session.execute(representative_snapshots.insert(), [" in source


def test_publication_is_atomic_and_notice_is_per_user():
    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")
    service = (ROOT / "app/services/ims_publication_service.py").read_text(encoding="utf-8")
    layout = (ROOT / "app/static/js/layout.js").read_text(encoding="utf-8")
    publish = worker[worker.index("def _prepare_and_publish"):]
    assert publish.index("dashboard_result = _warm_dashboard_snapshot") < publish.index("region_result = _warm_region_snapshots")
    assert publish.index("region_result = _warm_region_snapshots") < publish.index("representative_result = _warm_representative_snapshots(")
    assert 'summary["publication_ready"] = True' in worker
    assert 'stage="snapshot_retry"' in worker
    assert '"ims_publication_receipts"' in service
    assert "upload = cls.latest_visible_upload()" in service
    assert '"commit_upload", "final_checks", "read_models"' in service
    assert 'pending_progress.get("stage") in committed_unlinked_stages' in service
    assert "checkPublishedIMSNotice();" in layout
    assert "window.setInterval(checkPublishedIMSNotice, 15000);" in layout
    assert "ims-published-notice-layer" in layout
    assert "Yeni IMS başarıyla yüklendi" in layout
    assert "aria-modal" in layout


def test_notice_selects_current_visible_upload_not_historical_ready_job():
    service = (ROOT / "app/services/ims_publication_service.py").read_text(encoding="utf-8")
    notice_block = service[service.index("def notice_for_user"):service.index("def dismiss", service.index("def notice_for_user"))]
    assert "upload = cls.latest_visible_upload()" in notice_block
    assert "latest_ready_job" not in notice_block
    assert "db.session.get(IMSUpload" not in notice_block


def test_publication_receipt_does_not_hide_a_recycled_upload_id():
    service = (ROOT / "app/services/ims_publication_service.py").read_text(encoding="utf-8")
    assert "def _has_current_receipt" in service
    assert "ims_publication_receipts.c.dismissed_at" in service
    assert "dismissed_at.replace(microsecond=0)" in service
    assert "upload_ready_at.replace(microsecond=0)" in service
    assert "dismissed_second >= upload_ready_second" in service
    assert "ims_publication_receipts.delete().where(" in service
    assert "if cls._has_current_receipt(user_id, upload):" in service
    assert "upload is None or cls._has_current_receipt(user_id, upload)" in service
