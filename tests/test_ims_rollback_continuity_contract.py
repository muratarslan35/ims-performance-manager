from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_rollback_journal_is_sealed_before_snapshot_warmup_and_is_idempotent():
    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")
    lifecycle = (ROOT / "app/services/ims_upload_lifecycle_service.py").read_text(encoding="utf-8")
    publish = worker[
        worker.index("def _prepare_and_publish"):worker.index("def _retryable_publication_job")
    ]
    ensure = lifecycle[
        lifecycle.index("def ensure_snapshot_master_state_sealed"):
        lifecycle.index("def prepare_previous_rollback_assets")
    ]
    assert "def snapshot_master_state_sealed" in lifecycle
    assert "def ensure_snapshot_master_state_sealed" in lifecycle
    assert "if cls.snapshot_master_state_sealed(upload_id=upload_id)" in ensure
    assert "cls.seal_snapshot_master_state(upload_id=upload_id)" in ensure
    assert publish.index("ensure_snapshot_master_state_sealed") < publish.index(
        "dashboard_result = _warm_dashboard_snapshot"
    )
    assert "seal_snapshot_master_state(upload_id=completed.ims_upload_id)" not in publish


def test_active_legacy_upload_is_retried_but_historical_upload_is_not_sealed_from_current_state():
    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")
    retry = worker[worker.index("def _retryable_publication_job"):worker.index("def main()")] 
    publish = worker[
        worker.index("def _prepare_and_publish"):worker.index("def _retryable_publication_job")
    ]
    assert "latest_upload = IMSRosterSyncService.latest_completed_upload()" in retry
    assert "ims_upload_id=latest_upload.id" in retry
    assert "snapshot_master_state_sealed" in retry
    assert 'summary.get("publication_ready")' in retry
    assert 'roster_result.get("upload_id")' in publish
    assert "completed.ims_upload_id" in publish
    assert "Rollback journal sealing refused because the completed job is not the active IMS." in publish


def test_successive_rollbacks_prepare_the_newly_active_legacy_journal():
    lifecycle = (ROOT / "app/services/ims_upload_lifecycle_service.py").read_text(encoding="utf-8")
    ui = (ROOT / "app/services/ims_upload_lifecycle_ui.py").read_text(encoding="utf-8")
    standard = lifecycle[
        lifecycle.index("def rollback_to_previous"):lifecycle.index("def _invalidate_runtime_caches")
    ]
    first_period = ui[
        ui.index("def _rollback_first_period"):ui.index("def _inject_lifecycle_markup")
    ]
    assert "ensure_snapshot_master_state_sealed(upload_id=previous.id)" in standard
    assert "ensure_snapshot_master_state_sealed" in first_period
    assert "upload_id=previous_global.id" in first_period
