from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_final_ten_percent_is_reserved_for_real_read_model_work():
    queue = (ROOT / "app/services/ims_import_queue.py").read_text(encoding="utf-8")
    assert '"competition_import": (60, 90' in queue
    assert 'set_progress(92, "final_checks"' in queue
    assert '"region_snapshots"' in queue
    assert 'percent=94' not in queue  # queue helper uses positional percent
    assert '94,\n                    "read_models"' in queue
    assert '"Veriler ekrana aktarılıyor"' in queue


def test_completed_queue_row_can_keep_real_snapshot_progress_active():
    store = (ROOT / "app/services/ims_progress_store.py").read_text(encoding="utf-8")
    route = (ROOT / "app/routes/ims_progress.py").read_text(encoding="utf-8")
    assert 'POST_IMPORT_STAGES' in store
    assert '"dashboard_snapshot"' in store
    assert '"representative_snapshots"' in store
    assert 'stored.get("status") == job.STATUS_PROCESSING' in store
    assert '"active": payload.get("status")' in route


def test_worker_reports_dashboard_region_and_representative_snapshot_progress():
    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")
    assert 'percent=95' in worker
    assert 'stage="dashboard_snapshot"' in worker
    assert 'percent=96' in worker
    assert 'stage="region_snapshots"' in worker
    assert 'detail="Bölge analizleri doğrulanıyor"' in worker
    assert 'percent=97' in worker
    assert 'stage="representative_snapshots"' in worker
    assert 'value = 97 + round(2 * done / max(total, 1))' in worker
    assert 'eta_seconds' in worker
    assert 'tahmini' in worker
    assert 'percent=100' in worker
    assert 'IMS yüklemesi ve analiz ekranları hazır' in worker


def test_snapshot_progress_is_measured_not_random_or_timer_driven():
    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")
    ui = (ROOT / "app/static/js/layout.js").read_text(encoding="utf-8")
    assert 'done / max(total, 1)' in worker
    assert 'time.monotonic()' in worker
    assert 'Math.random' not in ui
    assert "fetch('/ims/progress'" in ui
