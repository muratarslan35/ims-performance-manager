from pathlib import Path


def test_latest_ims_keeps_rollback_control_visible_with_disabled_reason():
    template = Path("app/templates/ims.html").read_text()

    assert "item.id == latest_upload.id" in template
    assert "rollback_permission[1]" in template
    assert "Önceki IMS'e dön" in template
    assert "disabled title=" in template
