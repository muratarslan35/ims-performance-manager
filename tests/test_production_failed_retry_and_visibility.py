from pathlib import Path


def test_production_failed_retry_and_visibility_contract():
    source = Path("app/ims.py").read_text(encoding="utf-8")

    assert 'show_failed_production = request.args.get("show_failed_production") == "1"' in source
    assert "ProductionResultUpload.status != ProductionResultUpload.STATUS_FAILED" in source
    assert 'toggle_label = f"Hatalıları göster ({production_failed_count})"' in source

    assert "retrying_failed = existing is not None and existing.status == ProductionResultUpload.STATUS_FAILED" in source
    assert "existing.production_stage != production_stage" in source
    assert "upload = db.session.get(ProductionResultUpload, existing.id)" in source
    assert "production_stage=production_stage" in source

    # Successful duplicates remain blocked; only failed audit rows can be retried.
    assert "if existing is not None and not retrying_failed:" in source
    assert "if retrying_failed:" in source
