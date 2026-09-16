from pathlib import Path


def test_standard_rollback_is_direct_confirmed_post():
    template = Path("app/templates/ims.html").read_text(encoding="utf-8")
    assert "ims-rollback-direct-form" in template
    assert "url_for('ims.rollback_upload', upload_id=item.id)" in template
    assert "onsubmit=\"return window.confirm(" in template
    assert 'data-confirm-id="rollback-confirm-' not in template
    assert 'document.querySelectorAll(".ims-lifecycle-open")' not in template


def test_first_period_rollback_uses_real_post_form_not_hidden_panel_toggle():
    source = Path("app/services/ims_upload_lifecycle_ui.py").read_text(encoding="utf-8")
    assert "rollbackButton.dataset.firstPeriodRollback" in source
    assert "rollbackForm.method = 'post'" in source
    assert "rollbackForm.action = '/ims/uploads/' + id + '/rollback-first-period'" in source
    assert "rollbackForm.addEventListener('submit'" in source
    assert "window.confirm(" in source
    assert "panel.hidden = !panel.hidden" not in source
    assert "document.body.appendChild(panel)" not in source
