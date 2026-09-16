"""Inject narrowly scoped IMS history lifecycle controls without altering other UI."""
from __future__ import annotations

import json
from datetime import datetime

from flask import flash, redirect, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import AuditLog, IMSImportJob, IMSUpload
from app.services.ims_upload_lifecycle_service import IMSUploadLifecycleService


def _first_period_rollback_preflight(upload_id: int):
    """Allow the global latest IMS to return to its exact pre-import state.

    The core lifecycle service handles normal same-period rollback. This narrow
    fallback covers the first IMS of a newer month, where there is deliberately
    no previous upload in that month. The import snapshot already contains the
    exact pre-import state, so restoring it safely exposes the previous global
    completed IMS period again without touching any older period.
    """
    active_job = IMSImportJob.query.filter(
        IMSImportJob.status.in_((IMSImportJob.STATUS_QUEUED, IMSImportJob.STATUS_PROCESSING))
    ).first()
    if active_job is not None:
        raise RuntimeError("Aktif IMS importu varken geri dönüş yapılamaz.")

    upload = db.session.get(IMSUpload, int(upload_id))
    if upload is None:
        raise LookupError("IMS yüklemesi bulunamadı.")
    if upload.status != IMSUpload.STATUS_COMPLETED:
        raise RuntimeError("Yalnız sistemde aktif son IMS geri alınabilir.")

    latest_for_period = IMSUploadLifecycleService._latest_completed_for_period(upload)
    if latest_for_period is None or int(latest_for_period.id) != int(upload.id):
        raise RuntimeError("Yalnız aktif dönemin son IMS yüklemesi geri alınabilir.")

    global_latest = IMSUpload.query.filter_by(status=IMSUpload.STATUS_COMPLETED).order_by(
        IMSUpload.year.desc(), IMSUpload.month.desc(), IMSUpload.week_number.desc(),
        IMSUpload.completed_at.desc(), IMSUpload.id.desc(),
    ).first()
    if global_latest is None or int(global_latest.id) != int(upload.id):
        raise RuntimeError("Geçmiş dönem IMS'i değiştirilemez; yalnız sistemde aktif son IMS geri alınabilir.")

    previous_same_period = IMSUploadLifecycleService._previous_completed_for_period(upload)
    if previous_same_period is not None:
        raise RuntimeError("Bu IMS için standart aynı dönem geri dönüşü kullanılmalıdır.")

    from app.services.ims_rollback_guard import IMSRollbackGuard
    IMSRollbackGuard.assert_period_open(upload.year, upload.month)

    path = IMSUploadLifecycleService.upload_snapshot_path(upload.id)
    if not path.is_file():
        raise RuntimeError("Bu dönemin yükleme öncesi temiz IMS snapshot'ı bulunamadı.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("Geri dönüş snapshot'ı okunamıyor.") from exc

    if int(payload.get("version", 0)) < 3:
        raise RuntimeError("Bu IMS snapshot'ında eksiksiz geri dönüş günlüğü yok.")
    if (int(payload.get("year", 0)), int(payload.get("month", 0))) != (
        int(upload.year), int(upload.month)
    ):
        raise RuntimeError("Geri dönüş snapshot dönemi aktif IMS ile eşleşmiyor.")
    source_upload_id = payload.get("source_upload_id")
    if source_upload_id not in (None, 0, "", "0"):
        raise RuntimeError("Bu dönem ilk IMS değil; standart geri dönüş kullanılmalıdır.")
    if int(payload.get("sealed_upload_id", 0)) != int(upload.id):
        raise RuntimeError("IMS snapshot master günlüğü doğru yükleme için mühürlenmemiş.")
    if not payload.get("master_before") or not payload.get("master_after"):
        raise RuntimeError("IMS snapshot master değişiklik günlüğü eksik.")

    IMSUploadLifecycleService._validate_master_rollback(payload)

    from app.services.persistent_dashboard_snapshot_service import (
        PersistentDashboardSnapshotService,
    )
    active_ims_id, production_id = PersistentDashboardSnapshotService.source_identity(
        upload.year, upload.month
    )
    if int(active_ims_id or 0) != int(upload.id):
        raise RuntimeError("Aktif IMS kimliği geri dönüş hazırlığı sırasında değişti.")
    captured_production_id = int(payload.get("dashboard_production_upload_id", 0) or 0)
    if int(production_id or 0) != captured_production_id:
        raise RuntimeError(
            "IMS yüklemesinden sonra production kaynağı değişti; otomatik geri dönüş güvenli değil."
        )
    return upload, payload


def _first_period_rollback_permission(upload: IMSUpload) -> tuple[bool, str]:
    try:
        _first_period_rollback_preflight(upload.id)
    except (LookupError, RuntimeError) as exc:
        db.session.rollback()
        return False, str(exc)
    return True, ""


def _rollback_first_period(upload_id: int, *, actor: str | None = None) -> dict:
    upload, payload = _first_period_rollback_preflight(upload_id)
    year, month = int(upload.year), int(upload.month)
    try:
        IMSUploadLifecycleService._restore_period_snapshot(upload)
        master_result = IMSUploadLifecycleService._restore_master_state(payload)
        upload.status = IMSUpload.STATUS_ROLLED_BACK

        # No previous generation exists in this month. Supersede only this
        # month's active read-model sets; the previous global period remains
        # untouched and becomes the visible active period automatically.
        from app.services.persistent_region_snapshot_service import region_snapshot_sets
        from app.services.persistent_representative_snapshot_service import representative_snapshot_sets
        for table in (region_snapshot_sets, representative_snapshot_sets):
            db.session.execute(
                table.update().where(
                    table.c.year == year,
                    table.c.month == month,
                    table.c.status == "ACTIVE",
                ).values(status="SUPERSEDED")
            )

        db.session.add(AuditLog(
            username=(str(actor).strip() if actor else None),
            module="IMS",
            action=(
                f"IMS_ROLLBACK_FIRST_PERIOD from_upload={int(upload.id)} "
                f"period={year:04d}-{month:02d} "
                f"master_representatives={master_result['representatives']} "
                f"master_products={master_result['products']}"
            ),
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    IMSUploadLifecycleService._invalidate_runtime_caches(year, month)
    previous_global = IMSUpload.query.filter_by(status=IMSUpload.STATUS_COMPLETED).order_by(
        IMSUpload.year.desc(), IMSUpload.month.desc(), IMSUpload.week_number.desc(),
        IMSUpload.completed_at.desc(), IMSUpload.id.desc(),
    ).first()
    return {
        "rolled_back_upload_id": int(upload.id),
        "active_upload_id": int(previous_global.id) if previous_global else 0,
        "year": year,
        "month": month,
    }


def _inject_lifecycle_markup(rendered: str) -> str:
    hidden_ids = sorted(IMSUploadLifecycleService.hidden_upload_ids())
    permissions = {}
    for upload in IMSUpload.query.order_by(IMSUpload.id.desc()).all():
        allowed, reason = IMSUploadLifecycleService.can_delete(upload)
        permissions[str(upload.id)] = {"allowed": bool(allowed), "reason": reason or ""}

    first_period_rollbacks = {}
    latest_upload = IMSUpload.query.filter_by(status=IMSUpload.STATUS_COMPLETED).order_by(
        IMSUpload.year.desc(), IMSUpload.month.desc(), IMSUpload.week_number.desc(),
        IMSUpload.completed_at.desc(), IMSUpload.id.desc(),
    ).first()
    if latest_upload is not None:
        standard_allowed, _standard_reason = IMSUploadLifecycleService.can_rollback(latest_upload)
        if not standard_allowed:
            allowed, reason = _first_period_rollback_permission(latest_upload)
            first_period_rollbacks[str(latest_upload.id)] = {
                "allowed": bool(allowed),
                "reason": reason or "",
            }

    config = {
        "hiddenIds": hidden_ids,
        "showHidden": request.args.get("show_hidden") == "1",
        "deletePermissions": permissions,
        "firstPeriodRollbacks": first_period_rollbacks,
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
.ims-first-period-confirm {{ margin-top:6px; max-width:360px; }}
.ims-first-period-confirm .form-check-label {{ font-size:11px; line-height:1.35; }}
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

    const firstRollback = (cfg.firstPeriodRollbacks || {{}})[String(id)];
    if (firstRollback && firstRollback.allowed) {{
      const actionCell = row.children[8];
      const disabledRollback = actionCell && Array.from(actionCell.querySelectorAll('button[disabled]')).find((button) =>
        button.textContent.includes("Önceki IMS'e dön")
      );
      if (disabledRollback) {{
        disabledRollback.disabled = false;
        disabledRollback.removeAttribute('title');
        disabledRollback.classList.remove('btn-outline-secondary');
        disabledRollback.classList.add('btn-outline-warning');

        const panel = document.createElement('div');
        panel.className = 'alert alert-warning py-2 px-2 mb-0 w-100 ims-first-period-confirm';
        panel.hidden = true;
        panel.innerHTML = `
          <strong class="d-block mb-1" style="font-size:11px;">Bu dönem için daha eski IMS yok.</strong>
          <div class="small mb-2">Bu yükleme geri alınırsa dönem yükleme öncesi temiz durumuna döner ve bir önceki aktif IMS dönemi tekrar öne çıkar.</div>
          <form method="post" action="/ims/uploads/${{id}}/rollback-first-period">
            <div class="form-check mb-2">
              <input class="form-check-input" type="checkbox" required id="first-period-confirm-${{id}}">
              <label class="form-check-label" for="first-period-confirm-${{id}}">Bu IMS geri dönüşünü ve dönem temizliğini onaylıyorum.</label>
            </div>
            <div class="d-flex gap-1">
              <button class="btn btn-sm btn-warning" type="submit" style="font-size:11px;">Onayla ve geri al</button>
              <button class="btn btn-sm btn-light" type="button" data-first-period-cancel style="font-size:11px;">Vazgeç</button>
            </div>
          </form>`;
        disabledRollback.insertAdjacentElement('afterend', panel);
        disabledRollback.addEventListener('click', (event) => {{
          event.preventDefault();
          event.stopPropagation();
          panel.hidden = !panel.hidden;
        }});
        panel.addEventListener('click', (event) => event.stopPropagation());
        panel.querySelector('[data-first-period-cancel]')?.addEventListener('click', () => {{ panel.hidden = true; }});
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

    @login_required
    def rollback_first_period(upload_id: int):
        from app.ims import _require_ims_lifecycle_admin
        _require_ims_lifecycle_admin()
        try:
            result = _rollback_first_period(upload_id, actor=current_user.full_name)
        except (LookupError, RuntimeError) as exc:
            flash(str(exc), "warning")
        except Exception:
            db.session.rollback()
            app.logger.exception("ims_first_period_rollback_failed upload_id=%s", upload_id)
            flash("IMS geri alınamadı; mevcut dashboard verileri korunmuştur.", "danger")
        else:
            if result["active_upload_id"]:
                flash(
                    f"IMS #{result['rolled_back_upload_id']} geri alındı. "
                    f"Sistem önceki aktif IMS #{result['active_upload_id']} verisine geçti. "
                    "Geri alınan kayıt artık kalıcı temizlik için güvenle kaldırılabilir.",
                    "success",
                )
            else:
                flash(
                    f"IMS #{result['rolled_back_upload_id']} geri alındı ve dönem yükleme öncesi temiz duruma döndürüldü.",
                    "success",
                )
        return redirect(url_for("ims.index") + "#ims-history")

    if "ims_first_period_rollback" not in app.view_functions:
        app.add_url_rule(
            "/ims/uploads/<int:upload_id>/rollback-first-period",
            endpoint="ims_first_period_rollback",
            view_func=rollback_first_period,
            methods=["POST"],
        )

    def wrapped_index(*args, **kwargs):
        response = original(*args, **kwargs)
        if isinstance(response, str):
            return _inject_lifecycle_markup(response)
        return response

    wrapped_index._ims_lifecycle_ui_wrapped = True
    app.view_functions[endpoint] = wrapped_index
