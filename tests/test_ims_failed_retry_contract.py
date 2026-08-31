from pathlib import Path


def test_failed_source_is_preserved_for_retry():
    source = Path("app/services/ims_upload_lifecycle_hooks.py").read_text(encoding="utf-8")
    assert 'failed-job-{int(job.id)}' in source
    assert "pending_source.replace(failed_source)" in source
    assert "failed_source.unlink(missing_ok=True)" in source


def test_failed_retry_route_is_fail_closed_and_sha_guarded():
    source = Path("app/services/ims_failed_retry_ui.py").read_text(encoding="utf-8")
    assert '/ims/uploads/<int:upload_id>/retry' in source
    assert 'upload.status not in ("FAILED", "Hata")' in source
    assert "_active_job() is not None" in source
    assert "_sha256(source) != str(job.source_hash or \"\")" in source
    assert "_sha256(staging) != str(job.source_hash or \"\")" in source
    assert "job.status = IMSImportJob.STATUS_QUEUED" in source


def test_failed_rows_are_visible_and_retry_is_in_options_menu():
    source = Path("app/services/ims_upload_lifecycle_ui.py").read_text(encoding="utf-8")
    assert "Failed rows must stay visible" in source
    assert '/ims/uploads/${id}/retry' in source
    assert "Tekrar Dene" in source
    assert "data-ims-options-toggle" in source


def test_options_menu_has_native_click_fallback():
    source = Path("app/services/ims_upload_lifecycle_ui.py").read_text(encoding="utf-8")
    assert "menu.classList.toggle('show', opening)" in source
    assert "event.stopPropagation()" in source
    assert "document.addEventListener('click', () => closeMenus(null))" in source
