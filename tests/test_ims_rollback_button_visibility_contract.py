from pathlib import Path


def test_latest_ims_keeps_rollback_control_visible_with_disabled_reason():
    template = Path("app/templates/ims.html").read_text()

    assert "item.id == latest_upload.id" in template
    assert "rollback_permission[1]" in template
    assert "Önceki IMS'e dön" in template
    assert "disabled title=" in template


def test_rolled_back_delete_uses_direct_confirmed_post_form():
    template = Path("app/templates/ims.html").read_text()

    assert "url_for('ims.delete_upload', upload_id=item.id)" in template
    assert "onsubmit=\"return window.confirm(" in template
    assert 'data-confirm-id="delete-confirm-' not in template
