from pathlib import Path

from app.services.ims_upload_lifecycle_service import IMSUploadLifecycleService


def test_lifecycle_ui_is_scoped_to_ims_history_and_replace_defaults_safe():
    source = Path("app/services/ims_upload_lifecycle_ui.py").read_text(encoding="utf-8")
    assert 'endpoint = "ims.index"' in source
    assert "replaceInput.checked = false" in source
    assert "Aynı hafta farklı dosyaysa mevcut haftayı değiştir" in source
    assert "Gizle" in source
    assert "Göster" in source
    assert "IMS dosyasını kaldır" in source
    assert "window.confirm" in source


def test_options_dropdown_has_native_click_fallback():
    source = Path("app/services/ims_upload_lifecycle_ui.py").read_text(encoding="utf-8")
    assert "data-ims-options-toggle" in source
    assert "menu.classList.toggle('show', opening)" in source
    assert "document.addEventListener('click', () => closeMenus(null))" in source


def test_upload_route_rejects_exact_duplicate_and_requires_explicit_changed_week_replace():
    source = Path("app/ims.py").read_text(encoding="utf-8")
    assert "exact_duplicate_job(source_hash)" in source
    assert "aynı içerikle zaten mevcut" in source
    assert "existing_week.source_hash != source_hash and not replace_requested" in source
    assert "mevcut haftayı değiştir" in source


def test_explicit_replace_bypasses_duplicate_guards_for_parser_reprocessing():
    source = Path("app/services/ims_upload_lifecycle_hooks.py").read_text(encoding="utf-8")
    assert 'request.form.get("replace") == "1"' in source
    assert "return None" in source
    assert "not bool(job.clear_before_import)" in source
    assert "same_semantic_workbook" in source


def test_delete_gate_blocks_active_import_and_requires_snapshot_for_latest_completed():
    source = Path("app/services/ims_upload_lifecycle_service.py").read_text(encoding="utf-8")
    assert "STATUS_QUEUED" in source
    assert "STATUS_PROCESSING" in source
    assert "Aktif IMS importu varken silme yapılamaz" in source
    assert "upload_snapshot_path(upload.id).exists()" in source
    assert "geri dönüş snapshot" in source.lower()


def test_hide_is_metadata_only_not_an_ims_status_change():
    source = Path("app/services/ims_upload_lifecycle_service.py").read_text(encoding="utf-8")
    start = source.index("def set_hidden")
    end = source.index("def _latest_completed_for_period", start)
    block = source[start:end]
    assert "Setting" in block
    assert ".status" not in block


def test_rollback_snapshot_keeps_numeric_zero_by_value_not_truthiness():
    source = Path("app/services/ims_upload_lifecycle_service.py").read_text(encoding="utf-8")
    start = source.index("def _serialize_rows")
    end = source.index("def capture_period_snapshot", start)
    block = source[start:end]
    assert "if value:" not in block
    assert "values[column.name] = value" in block


def test_archive_is_created_only_for_successful_queue_result():
    source = Path("app/services/ims_upload_lifecycle_hooks.py").read_text(encoding="utf-8")
    assert "refreshed.status == IMSImportJob.STATUS_COMPLETED" in source
    assert "archive_successful_source" in source
    assert "discard_pending_snapshot" in source


def test_lifecycle_archive_does_not_change_priority_or_prime_code():
    for path in (
        "app/services/ims_upload_lifecycle_service.py",
        "app/services/ims_upload_lifecycle_hooks.py",
        "app/services/ims_upload_lifecycle_ui.py",
    ):
        source = Path(path).read_text(encoding="utf-8")
        assert "ProductionResult" not in source
        assert "PrimeRule" not in source
        assert "bonus_amount" not in source
