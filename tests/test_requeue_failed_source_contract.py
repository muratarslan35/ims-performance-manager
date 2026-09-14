from pathlib import Path


def test_requeue_accepts_hash_verified_failed_job_source():
    source = Path("scripts/requeue_latest_empty_ims.py").read_text()

    assert "failed_source_for_job(job.id)" in source
    assert 'source_kind = "verified_failed_job"' in source
    assert "preserved_source_not_found" in source
    assert "_file_sha256(source) != expected_hash" in source


def test_failed_source_lookup_is_shared_with_retry_ui():
    lifecycle = Path("app/services/ims_upload_lifecycle_service.py").read_text()
    retry_ui = Path("app/services/ims_failed_retry_ui.py").read_text()

    assert "def failed_source_for_job" in lifecycle
    assert 'f"failed-job-{int(job_id)}{suffix}"' in lifecycle
    assert "IMSUploadLifecycleService.failed_source_for_job(job.id)" in retry_ui
