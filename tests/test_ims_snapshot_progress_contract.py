from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_progress_weight_matches_observed_import_and_read_model_work():
    queue = (ROOT / "app/services/ims_import_queue.py").read_text(encoding="utf-8")
    assert '"competition_import": (28, 38' in queue
    assert 'set_progress(40, "final_checks"' in queue
    assert '41,\n                    "read_models"' in queue
    assert '"Veriler ekrana aktarılıyor"' in queue


def test_completed_queue_row_remains_visibly_processing_until_publication():
    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")
    route = (ROOT / "app/routes/ims_progress.py").read_text(encoding="utf-8")
    post_import = worker[worker.index("if completed is not None and completed.status") :]
    assert post_import.count('status=IMSImportJob.STATUS_PROCESSING') >= 3
    assert 'summary["publication_ready"] = True' in post_import
    assert '"active": payload.get("status")' in route


def test_worker_reports_dashboard_region_and_representative_snapshot_progress():
    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")
    assert 'percent=95' in worker
    assert 'stage="dashboard_snapshot"' in worker
    assert 'percent=97' in worker
    assert 'stage="region_snapshots"' in worker
    assert 'Bölge snapshotları hazırlanıyor' in worker
    assert 'percent=42' in worker
    assert 'stage="representative_snapshots"' in worker
    assert 'value = 42 + round(52 * done / max(total, 1))' in worker
    assert 'eta_seconds' in worker
    assert 'tahmini' in worker
    assert 'percent=100' in worker
    assert 'IMS yüklemesi tamamlandı · snapshot alındı' in worker
    assert 'IMS yüklemesi tamamlandı · snapshotların bir kısmı alınamadı' in worker
    assert 'Snapshot durumu · Dashboard:' in worker


def test_snapshot_failure_blocks_publication_but_preserves_imported_data():
    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")
    assert 'def _snapshot_label' in worker
    assert 'return "alındı"' in worker
    assert 'else "alınamadı"' in worker
    assert 'completed.status = IMSImportJob.STATUS_FAILED' in worker
    assert 'snapshot doğrulaması tamamlanamadığı için yayınlanmadı' in worker


def test_snapshot_progress_is_measured_not_random_or_timer_driven():
    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")
    ui = (ROOT / "app/static/js/layout.js").read_text(encoding="utf-8")
    assert 'done / max(total, 1)' in worker
    assert 'time.monotonic()' in worker
    assert 'Math.random' not in ui
    assert "fetch('/ims/progress'" in ui
