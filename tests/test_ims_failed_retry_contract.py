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
    assert "_recover_orphaned_failed_job(upload)" in source
    assert "distance > 120" in source
    assert "job.ims_upload_id = upload.id" in source
    assert "candidate.stored_file_name" in source


def test_failed_import_links_audit_upload_before_queue_failure():
    source = Path("app/services/ims_import_queue.py").read_text(encoding="utf-8")
    assert 'failure_upload_id = result.get("upload_id")' in source
    assert "linked_job.ims_upload_id = int(failure_upload_id)" in source
    assert "db.session.commit()" in source


def test_late_post_import_failure_keeps_upload_link_for_retry():
    source = Path("app/services/ims_import_queue.py").read_text(encoding="utf-8")
    assert "late_upload_id = result.get" in source
    assert "failed.ims_upload_id = int(late_upload_id)" in source
    assert 'late_upload.status = "FAILED"' in source


def test_retry_reuses_one_audit_upload_and_preserves_display_name():
    queue = Path("app/services/ims_import_queue.py").read_text(encoding="utf-8")
    retry = Path("app/services/ims_failed_retry_ui.py").read_text(encoding="utf-8")
    assert "create_retry_upload" in queue
    assert "service.create_upload = MethodType" in queue
    assert "upload.file_name = job.file_name" in retry
    assert "Tekrarlanan IMS yeniden deneme kaydı" in retry


def test_failed_ims_reason_stays_visible_in_history():
    source = Path("app/templates/ims.html").read_text(encoding="utf-8")
    assert "item.error_message" in source
    assert "Hata nedeni:" in source


def test_failed_rows_are_visible_and_retry_is_in_options_menu():
    source = Path("app/services/ims_upload_lifecycle_ui.py").read_text(encoding="utf-8")
    assert "Failed rows must stay visible" in source
    # Python f-string source escapes JS template braces as ${{id}}; rendered JS is ${id}.
    assert '/ims/uploads/${{id}}/retry' in source
    assert "Tekrar Dene" in source
    assert "data-ims-options-toggle" in source


def test_options_menu_has_native_click_fallback():
    source = Path("app/services/ims_upload_lifecycle_ui.py").read_text(encoding="utf-8")
    assert "menu.classList.toggle('show', opening)" in source
    assert "event.stopPropagation()" in source
    assert "document.addEventListener('click', () => closeMenus(null))" in source
