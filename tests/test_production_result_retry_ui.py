from pathlib import Path


def test_production_result_retry_ui_contract():
    source = Path("app/services/production_result_retry_ui.py").read_text(encoding="utf-8")
    app_source = Path("app/__init__.py").read_text(encoding="utf-8")
    ims_source = Path("app/ims.py").read_text(encoding="utf-8")

    assert '"/ims/production-uploads/<int:upload_id>/retry"' in source
    assert "ProductionResultUpload.STATUS_FAILED" in source
    assert "_active_ims_job() is not None" in source
    assert "_source_hash(stored_path) != upload.source_hash" in source
    assert "production_stage=upload.production_stage" in source
    assert "ProductionResultImportService.apply(upload, report)" in source
    assert "failed.status = ProductionResultUpload.STATUS_FAILED" in source
    assert "Tekrar Dene" in source
    assert "bi-arrow-clockwise" in source

    # No failed-history hide/show workflow: failed rows stay visible and are retried in place.
    assert "show_failed_production" not in ims_source
    assert "Hatalıları göster" not in ims_source

    assert "install_production_result_retry_ui" in app_source
