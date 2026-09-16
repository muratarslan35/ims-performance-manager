from pathlib import Path


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label} not found; refusing broad edit")
    return text.replace(old, new, 1)


service_path = Path("app/services/ims_upload_lifecycle_ui.py")
service = service_path.read_text(encoding="utf-8")
start_marker = "    const firstRollback = (cfg.firstPeriodRollbacks || {{}})[String(id)];"
end_marker = "    if (row.querySelector('.ims-lifecycle-cell')) return;"
start = service.find(start_marker)
end = service.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit("First-period rollback UI block not found; refusing broad edit")

first_period_replacement = r'''    const firstRollback = (cfg.firstPeriodRollbacks || {{}})[String(id)];
    if (firstRollback && firstRollback.allowed) {{
      const actionCell = row.children[8];
      const rollbackButton = actionCell && Array.from(actionCell.querySelectorAll('button')).find((button) =>
        button.textContent.includes("Önceki IMS'e dön")
      );
      if (rollbackButton) {{
        rollbackButton.disabled = false;
        rollbackButton.removeAttribute('disabled');
        rollbackButton.removeAttribute('title');
        rollbackButton.classList.remove('btn-outline-secondary');
        rollbackButton.classList.add('btn-outline-warning');
        rollbackButton.type = 'submit';
        rollbackButton.dataset.firstPeriodRollback = String(id);

        let rollbackForm = rollbackButton.closest('[data-first-period-rollback-form]');
        if (!rollbackForm) {{
          rollbackForm = document.createElement('form');
          rollbackForm.method = 'post';
          rollbackForm.action = '/ims/uploads/' + id + '/rollback-first-period';
          rollbackForm.dataset.firstPeriodRollbackForm = '1';
          rollbackForm.style.display = 'inline-block';
          rollbackButton.parentNode.insertBefore(rollbackForm, rollbackButton);
          rollbackForm.appendChild(rollbackButton);
        }}

        rollbackForm.addEventListener('submit', (event) => {{
          const period = (row.dataset.year || '') + '/' + (row.dataset.month || '');
          const week = row.dataset.week ? ' ' + row.dataset.week + '. hafta' : '';
          const confirmed = window.confirm(
            period + week + ' IMS geri alınacak. ' +
            'Bu dönem yükleme öncesi temiz duruma dönecek ve bir önceki aktif IMS tekrar öne çıkacak. Devam edilsin mi?'
          );
          if (!confirmed) {{
            event.preventDefault();
            return;
          }}
          rollbackButton.disabled = true;
          rollbackButton.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>Geri alınıyor...';
        }});
      }}
    }}

'''
service = service[:start] + first_period_replacement + service[end:]
service_path.write_text(service, encoding="utf-8")


template_path = Path("app/templates/ims.html")
template = template_path.read_text(encoding="utf-8")
standard_old = '''              <button class="btn btn-sm btn-outline-warning py-1 px-2 ims-lifecycle-open" type="button" style="font-size:11px;" data-confirm-id="rollback-confirm-{{ item.id }}"><i class="bi bi-arrow-counterclockwise me-1"></i>Önceki IMS'e dön</button>
              <div class="alert alert-warning py-2 px-2 mb-0 w-100 ims-lifecycle-confirm" id="rollback-confirm-{{ item.id }}" hidden>
                <strong class="d-block mb-1" style="font-size:11px;">Son IMS geri alınacak. Emin misiniz?</strong>
                <form class="d-flex gap-1" method="post" action="{{ url_for('ims.rollback_upload', upload_id=item.id) }}">
                  <button class="btn btn-sm btn-warning" type="submit" style="font-size:11px;">Onayla ve geri al</button>
                  <button class="btn btn-sm btn-light ims-lifecycle-cancel" type="button" style="font-size:11px;">Vazgeç</button>
                </form>
              </div>'''
standard_new = '''              <form method="post" action="{{ url_for('ims.rollback_upload', upload_id=item.id) }}" class="d-inline-block ims-rollback-direct-form" onsubmit="return window.confirm('Son aktif IMS geri alınacak ve aynı dönemdeki bir önceki doğrulanmış IMS yeniden aktif olacak. Devam edilsin mi?');">
                <button class="btn btn-sm btn-outline-warning py-1 px-2" type="submit" style="font-size:11px;"><i class="bi bi-arrow-counterclockwise me-1"></i>Önceki IMS'e dön</button>
              </form>'''
template = replace_once(template, standard_old, standard_new, label="Standard rollback confirmation block")

legacy_js = '''  document.querySelectorAll(".ims-lifecycle-open").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      document.querySelectorAll(".ims-lifecycle-confirm").forEach((panel) => { panel.hidden = true; });
      const panel = document.getElementById(button.dataset.confirmId);
      if (panel) panel.hidden = false;
    });
  });
  document.querySelectorAll(".ims-lifecycle-confirm").forEach((panel) => {
    panel.addEventListener("click", (event) => event.stopPropagation());
  });
  document.querySelectorAll(".ims-lifecycle-cancel").forEach((button) => {
    button.addEventListener("click", () => { button.closest(".ims-lifecycle-confirm").hidden = true; });
  });

'''
template = replace_once(template, legacy_js, "", label="Legacy rollback click wiring")
template_path.write_text(template, encoding="utf-8")


contract_path = Path("tests/test_ims_upload_lifecycle_contract.py")
contract = contract_path.read_text(encoding="utf-8")
old_contract = '''    assert 'type="button"' in template
    assert "Onayla ve geri al" in template
    assert "Onayla ve kalıcı sil" in template
    assert "ims-lifecycle-confirm" in template'''
new_contract = '''    assert "ims-rollback-direct-form" in template
    assert 'onsubmit="return window.confirm(' in template
    assert "Önceki IMS'e dön" in template
    assert "Onayla ve kalıcı sil" in template'''
contract = replace_once(contract, old_contract, new_contract, label="Lifecycle interaction contract")
contract_path.write_text(contract, encoding="utf-8")


interaction_test = Path("tests/test_ims_rollback_interaction_contract.py")
interaction_test.write_text(
    '''from pathlib import Path\n\n\ndef test_standard_rollback_is_direct_confirmed_post():\n    template = Path("app/templates/ims.html").read_text(encoding="utf-8")\n    assert "ims-rollback-direct-form" in template\n    assert "url_for('ims.rollback_upload', upload_id=item.id)" in template\n    assert "onsubmit=\\\"return window.confirm(" in template\n    assert 'data-confirm-id="rollback-confirm-' not in template\n    assert 'document.querySelectorAll(".ims-lifecycle-open")' not in template\n\n\ndef test_first_period_rollback_uses_real_post_form_not_hidden_panel_toggle():\n    source = Path("app/services/ims_upload_lifecycle_ui.py").read_text(encoding="utf-8")\n    assert "rollbackButton.dataset.firstPeriodRollback" in source\n    assert "rollbackForm.method = 'post'" in source\n    assert "rollbackForm.action = '/ims/uploads/' + id + '/rollback-first-period'" in source\n    assert "rollbackForm.addEventListener('submit'" in source\n    assert "window.confirm(" in source\n    assert "panel.hidden = !panel.hidden" not in source\n    assert "document.body.appendChild(panel)" not in source\n''',
    encoding="utf-8",
)

print("IMS rollback interaction repair prepared")
