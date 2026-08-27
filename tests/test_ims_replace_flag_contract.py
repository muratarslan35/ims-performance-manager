from pathlib import Path


def test_ims_upload_forwards_same_period_replace_flag_to_background_job():
    route = Path("app/ims.py").read_text(encoding="utf-8")
    start = route.index("def upload():")
    end = route.index('@ims_bp.route("/import-jobs"', start)
    upload_block = route[start:end]

    assert 'clear_before_import=request.form.get("replace") == "1"' in upload_block
    assert "clear_before_import=False" not in upload_block


def test_ims_form_and_queue_keep_replace_contract_aligned():
    template = Path("app/templates/ims.html").read_text(encoding="utf-8")
    queue = Path("app/services/ims_import_queue.py").read_text(encoding="utf-8")

    assert 'name="replace" value="1"' in template
    assert "clear_before_import=job.clear_before_import" in queue
