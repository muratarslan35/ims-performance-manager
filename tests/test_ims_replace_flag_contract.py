from pathlib import Path


def test_ims_upload_forwards_same_period_replace_flag_to_background_job():
    route = Path("app/ims.py").read_text(encoding="utf-8")
    start = route.index("def upload():")
    end = route.index('@ims_bp.route("/import-jobs"', start)
    upload_block = route[start:end]

    # The lifecycle route reads the switch once so it can use the same explicit
    # decision both for the changed-week warning and for the queued replace job.
    assert 'replace_requested = request.form.get("replace") == "1"' in upload_block
    assert "clear_before_import=replace_requested" in upload_block
    assert "clear_before_import=False" not in upload_block


def test_ims_form_and_queue_keep_replace_contract_aligned():
    template = Path("app/templates/ims.html").read_text(encoding="utf-8")
    queue = Path("app/services/ims_import_queue.py").read_text(encoding="utf-8")
    lifecycle_ui = Path("app/services/ims_upload_lifecycle_ui.py").read_text(encoding="utf-8")

    assert 'name="replace" value="1"' in template
    assert "replaceInput.checked = false" in lifecycle_ui
    assert "clear_before_import=job.clear_before_import" in queue
