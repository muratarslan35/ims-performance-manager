"""Inject narrowly scoped IMS history lifecycle controls without altering other UI."""
from __future__ import annotations

import json

from flask import request

from app.models import IMSUpload
from app.services.ims_upload_lifecycle_service import IMSUploadLifecycleService


def _inject_lifecycle_markup(rendered: str) -> str:
    hidden_ids = sorted(IMSUploadLifecycleService.hidden_upload_ids())
    permissions = {}
    for upload in IMSUpload.query.order_by(IMSUpload.id.desc()).all():
        allowed, reason = IMSUploadLifecycleService.can_delete(upload)
        permissions[str(upload.id)] = {"allowed": bool(allowed), "reason": reason or ""}

    config = {
        "hiddenIds": hidden_ids,
        "showHidden": request.args.get("show_hidden") == "1",
        "deletePermissions": permissions,
    }
    payload = json.dumps(config, ensure_ascii=False).replace("</", "<\\/")
    script = f"""
<style>
.ims-lifecycle-cell {{ min-width: 108px; position:relative; overflow:visible; }}
.ims-hidden-badge {{ margin-left:6px;font-size:10px;vertical-align:middle; }}
.ims-lifecycle-dropdown .dropdown-item {{ font-size:12px; }}
.ims-lifecycle-dropdown form {{ margin:0; }}
.ims-lifecycle-dropdown .dropdown-menu.show {{ display:block; z-index:1080; }}
#imsHistoryTable, #imsHistoryTable tbody, #imsHistoryTable tr {{ overflow:visible; }}
</style>
<script>
(function() {{
  const cfg = {payload};
  const hiddenIds = new Set((cfg.hiddenIds || []).map(Number));

  const replaceInput = document.querySelector('#imsUploadForm input[name="replace"]');
  if (replaceInput) {{
    replaceInput.checked = false;
    const label = replaceInput.closest('.form-check')?.querySelector('.form-check-label');
    if (label) label.textContent = 'Aynı hafta farklı dosyaysa mevcut haftayı değiştir';
  }}

  const controls = document.querySelector('#ims-history .ims-history-controls');
  if (controls && hiddenIds.size) {{
    const toggle = document.createElement('a');
    toggle.className = 'ims-export-btn';
    const url = new URL(window.location.href);
    if (cfg.showHidden) {{
      url.searchParams.delete('show_hidden');
      toggle.innerHTML = '<i class="bi bi-eye-slash"></i> Gizlenenleri kapat';
    }} else {{
      url.searchParams.set('show_hidden', '1');
      toggle.innerHTML = '<i class="bi bi-eye"></i> Gizlenenleri göster';
    }}
    url.hash = 'ims-history';
    toggle.href = url.toString();
    controls.appendChild(toggle);
  }}

  const table = document.getElementById('imsHistoryTable');
  if (!table) return;
  const headerRow = table.querySelector('thead tr');
  if (headerRow && !headerRow.querySelector('[data-ims-lifecycle-header]')) {{
    const th = document.createElement('th');
    th.dataset.imsLifecycleHeader = '1';
    th.textContent = 'Seçenekler';
    th.style.cssText = 'font-size:11px;font-weight:700;text-transform:uppercase;color:#5f7188;padding:12px 16px;border-bottom:1px solid rgba(11,78,162,.12);';
    headerRow.appendChild(th);
  }}

  function closeMenus(except) {{
    table.querySelectorAll('.ims-lifecycle-dropdown .dropdown-menu.show').forEach((menu) => {{
      if (menu === except) return;
      menu.classList.remove('show');
      const button = menu.closest('.ims-lifecycle-dropdown')?.querySelector('[data-ims-options-toggle]');
      if (button) button.setAttribute('aria-expanded', 'false');
    }});
  }}

  table.querySelectorAll('.ims-history-row').forEach((row) => {{
    const id = Number(row.dataset.id || 0);
    const isHidden = hiddenIds.has(id);
    const isFailed = ['FAILED', 'Hata'].includes(row.dataset.status);

    // Failed rows must stay visible so the administrator can inspect/retry them.
    // Explicit lifecycle hiding still wins when the user intentionally hid a row.
    if (isFailed && !isHidden) {{
      row.hidden = false;
      row.removeAttribute('aria-hidden');
    }} else if (isHidden && !cfg.showHidden) {{
      row.hidden = true;
      row.setAttribute('aria-hidden', 'true');
    }}
    if (isHidden && cfg.showHidden) {{
      row.hidden = false;
      row.removeAttribute('aria-hidden');
      const fileCell = row.children[1];
      if (fileCell && !fileCell.querySelector('.ims-hidden-badge')) {{
        const badge = document.createElement('span');
        badge.className = 'badge bg-secondary ims-hidden-badge';
        badge.textContent = 'Gizli';
        fileCell.appendChild(badge);
      }}
    }}

    if (row.querySelector('.ims-lifecycle-cell')) return;
    const td = document.createElement('td');
    td.className = 'ims-lifecycle-cell';
    td.style.padding = '12px 16px';

    const permission = (cfg.deletePermissions || {{}})[String(id)] || {{allowed:false, reason:'Silme güvenliği doğrulanamadı.'}};
    const visibilityAction = isHidden ? 'show' : 'hide';
    const visibilityLabel = isHidden ? 'Göster' : 'Gizle';
    const visibilityIcon = isHidden ? 'bi-eye' : 'bi-eye-slash';
    const retryItem = isFailed ? `
          <li>
            <form method="post" action="/ims/uploads/${{id}}/retry" data-ims-retry-form>
              <button class="dropdown-item text-primary" type="submit"><i class="bi bi-arrow-clockwise me-2"></i>Tekrar Dene</button>
            </form>
          </li>
          <li><hr class="dropdown-divider"></li>` : '';

    td.innerHTML = `
      <div class="dropdown ims-lifecycle-dropdown">
        <button class="btn btn-sm btn-outline-secondary dropdown-toggle py-1 px-2" type="button" data-ims-options-toggle aria-expanded="false" style="font-size:11px;">Seçenekler</button>
        <ul class="dropdown-menu dropdown-menu-end">
          ${{retryItem}}
          <li>
            <form method="post" action="/ims/uploads/${{id}}/${{visibilityAction}}">
              <button class="dropdown-item" type="submit"><i class="bi ${{visibilityIcon}} me-2"></i>${{visibilityLabel}}</button>
            </form>
          </li>
          <li><hr class="dropdown-divider"></li>
          <li>
            <form method="post" action="/ims/uploads/${{id}}/delete" data-ims-delete-form>
              <button class="dropdown-item text-danger" type="submit" ${{permission.allowed ? '' : 'disabled'}} title="${{String(permission.reason || '').replace(/\"/g, '&quot;')}}"><i class="bi bi-trash3 me-2"></i>IMS dosyasını kaldır</button>
            </form>
          </li>
        </ul>
      </div>`;

    const toggleButton = td.querySelector('[data-ims-options-toggle]');
    const menu = td.querySelector('.dropdown-menu');
    if (toggleButton && menu) {{
      toggleButton.addEventListener('click', (event) => {{
        event.preventDefault();
        event.stopPropagation();
        const opening = !menu.classList.contains('show');
        closeMenus(menu);
        menu.classList.toggle('show', opening);
        toggleButton.setAttribute('aria-expanded', opening ? 'true' : 'false');
      }});
      menu.addEventListener('click', (event) => event.stopPropagation());
    }}

    const retryForm = td.querySelector('[data-ims-retry-form]');
    if (retryForm) {{
      retryForm.addEventListener('submit', () => {{
        const badge = row.querySelector('.badge.bg-danger');
        if (badge) {{
          badge.className = 'badge bg-warning text-dark';
          badge.textContent = 'Kuyruğa alınıyor';
        }}
        const button = retryForm.querySelector('button');
        if (button) {{
          button.disabled = true;
          button.innerHTML = '<i class="bi bi-hourglass-split me-2"></i>Yeniden işleniyor';
        }}
      }});
    }}

    const deleteForm = td.querySelector('[data-ims-delete-form]');
    if (deleteForm && permission.allowed) {{
      deleteForm.addEventListener('submit', (event) => {{
        if (!window.confirm('Bu IMS tamamen silinecek. Son aktif IMS ise dashboard önceki güvenli IMS durumuna döndürülecek. Devam edilsin mi?')) {{
          event.preventDefault();
        }}
      }});
    }}
    row.appendChild(td);
  }});

  document.addEventListener('click', () => closeMenus(null));
  const emptyRow = table.querySelector('tbody tr:not(.ims-history-row) td[colspan]');
  if (emptyRow) emptyRow.colSpan = 10;
}})();
</script>
"""
    if "</body>" in rendered:
        return rendered.replace("</body>", script + "</body>", 1)
    return rendered + script


def install_ims_upload_lifecycle_ui(app) -> None:
    endpoint = "ims.index"
    original = app.view_functions.get(endpoint)
    if original is None or getattr(original, "_ims_lifecycle_ui_wrapped", False):
        return

    def wrapped_index(*args, **kwargs):
        response = original(*args, **kwargs)
        if isinstance(response, str):
            return _inject_lifecycle_markup(response)
        return response

    wrapped_index._ims_lifecycle_ui_wrapped = True
    app.view_functions[endpoint] = wrapped_index
