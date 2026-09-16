from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"{label} not found in {path}; refusing broad edit")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1) Rollback journal: seal exactly once and make sequential legacy rollback self-healing.
service_path = Path("app/services/ims_upload_lifecycle_service.py")
service = service_path.read_text(encoding="utf-8")
service_marker = '''        cls._write_snapshot_payload(path, payload)\n        return path\n\n    @classmethod\n    def prepare_previous_rollback_assets'''
service_replacement = '''        cls._write_snapshot_payload(path, payload)\n        return path\n\n    @classmethod\n    def snapshot_master_state_sealed(cls, *, upload_id: int) -> bool:\n        \"\"\"Return whether one finalized upload has a complete immutable master journal.\"\"\"\n        path = cls.upload_snapshot_path(upload_id)\n        if not path.is_file():\n            return False\n        try:\n            payload = json.loads(path.read_text(encoding=\"utf-8\"))\n        except (OSError, ValueError, TypeError):\n            return False\n        return (\n            int(payload.get(\"version\", 0)) == cls.SNAPSHOT_VERSION\n            and int(payload.get(\"sealed_upload_id\", 0) or 0) == int(upload_id)\n            and bool(payload.get(\"master_before\"))\n            and bool(payload.get(\"master_after\"))\n        )\n\n    @classmethod\n    def ensure_snapshot_master_state_sealed(cls, *, upload_id: int) -> bool:\n        \"\"\"Seal a missing journal once; never overwrite an existing post-import baseline.\"\"\"\n        if cls.snapshot_master_state_sealed(upload_id=upload_id):\n            return False\n        cls.seal_snapshot_master_state(upload_id=upload_id)\n        return True\n\n    @classmethod\n    def prepare_previous_rollback_assets'''
if service_marker not in service:
    raise SystemExit("rollback seal insertion point not found")
service = service.replace(service_marker, service_replacement, 1)

start = service.index("    def rollback_to_previous(")
end = service.index("    @staticmethod\n    def _invalidate_runtime_caches", start)
block = service[start:end]
old_tail = '''            db.session.commit()\n        except Exception:\n            db.session.rollback()\n            raise\n        cls._invalidate_runtime_caches(year, month)\n        return {'''
new_tail = '''            db.session.commit()\n        except Exception:\n            db.session.rollback()\n            raise\n\n        # Legacy imports created before journal sealing was decoupled from the\n        # read-model warm-up can become active after a successful rollback.\n        # At this point the authoritative master state has already been restored\n        # to that previous upload, so seal its missing journal once.  Existing\n        # sealed journals are immutable and are never overwritten.\n        try:\n            if cls.ensure_snapshot_master_state_sealed(upload_id=previous.id):\n                current_app.logger.info(\n                    \"ims_rollback_previous_master_journal_sealed upload_id=%s\", previous.id\n                )\n        except Exception:\n            current_app.logger.exception(\n                \"ims_rollback_previous_master_journal_seal_failed upload_id=%s\", previous.id\n            )\n\n        cls._invalidate_runtime_caches(year, month)\n        return {'''
if old_tail not in block:
    raise SystemExit("rollback continuity insertion point not found")
block = block.replace(old_tail, new_tail, 1)
service = service[:start] + block + service[end:]
service_path.write_text(service, encoding="utf-8")


# 2) First-period rollback: the previous global IMS must also be immediately rollback-ready.
ui_path = Path("app/services/ims_upload_lifecycle_ui.py")
ui = ui_path.read_text(encoding="utf-8")
old_first_tail = '''    previous_global = IMSUpload.query.filter_by(status=IMSUpload.STATUS_COMPLETED).order_by(\n        IMSUpload.year.desc(), IMSUpload.month.desc(), IMSUpload.week_number.desc(),\n        IMSUpload.completed_at.desc(), IMSUpload.id.desc(),\n    ).first()\n    return {'''
new_first_tail = '''    previous_global = IMSUpload.query.filter_by(status=IMSUpload.STATUS_COMPLETED).order_by(\n        IMSUpload.year.desc(), IMSUpload.month.desc(), IMSUpload.week_number.desc(),\n        IMSUpload.completed_at.desc(), IMSUpload.id.desc(),\n    ).first()\n    if previous_global is not None:\n        try:\n            if IMSUploadLifecycleService.ensure_snapshot_master_state_sealed(\n                upload_id=previous_global.id\n            ):\n                current_app.logger.info(\n                    \"ims_first_period_previous_master_journal_sealed upload_id=%s\",\n                    previous_global.id,\n                )\n        except Exception:\n            current_app.logger.exception(\n                \"ims_first_period_previous_master_journal_seal_failed upload_id=%s\",\n                previous_global.id,\n            )\n    return {'''
if old_first_tail not in ui:
    raise SystemExit("first-period rollback continuity insertion point not found")
ui_path.write_text(ui.replace(old_first_tail, new_first_tail, 1), encoding="utf-8")


# 3) Future uploads: create the rollback master journal immediately after the business import,
#    before long/retryable dashboard/region/representative snapshot work.
worker_path = Path("ims_import_worker.py")
worker = worker_path.read_text(encoding="utf-8")
old_begin = '''def _prepare_and_publish(app, completed):\n    \"\"\"Retryable read-model publication; the committed IMS always stays valid.\"\"\"\n    job_id, year, month = completed.id, completed.year, completed.month\n    IMSProgressStore.write(job_id, percent=42, stage=\"dashboard_snapshot\",'''
new_begin = '''def _prepare_and_publish(app, completed):\n    \"\"\"Retryable read-model publication; the committed IMS always stays valid.\"\"\"\n    job_id, year, month = completed.id, completed.year, completed.month\n\n    # Rollback safety is a business-import contract, not a snapshot-readiness\n    # contract. Seal it before the long read-model warm-up so a region/rep\n    # snapshot failure can never leave a valid IMS with a disabled rollback.\n    if completed.ims_upload_id is None:\n        raise RuntimeError(\"Completed IMS job has no upload id for rollback journal sealing.\")\n    if not IMSUploadLifecycleService.snapshot_master_state_sealed(\n        upload_id=completed.ims_upload_id\n    ):\n        try:\n            roster_result = IMSRosterSyncService.sync_latest()\n            if int(roster_result.get(\"upload_id\") or 0) != int(completed.ims_upload_id):\n                raise RuntimeError(\n                    \"Rollback journal sealing refused because the completed job is not the active IMS.\"\n                )\n            app.logger.info(\"ims_roster_sync_success %s\", roster_result)\n            IMSUploadLifecycleService.ensure_snapshot_master_state_sealed(\n                upload_id=completed.ims_upload_id\n            )\n            app.logger.info(\n                \"ims_rollback_master_journal_ready upload_id=%s job_id=%s\",\n                completed.ims_upload_id, job_id,\n            )\n        except Exception:\n            db.session.rollback()\n            refreshed = db.session.get(IMSImportJob, job_id)\n            if refreshed is not None:\n                refreshed.error_message = (\n                    \"IMS başarıyla işlendi; geri dönüş güvenlik günlüğü otomatik olarak yeniden denenecek.\"\n                )\n                db.session.commit()\n            IMSProgressStore.write(\n                job_id, percent=41, stage=\"snapshot_retry\",\n                message=\"IMS yüklendi · güvenlik günlüğü yeniden denenecek\",\n                detail=\"Geri dönüş güvenlik günlüğü tamamlanamadı; mevcut IMS verileri korunuyor.\",\n                status=IMSImportJob.STATUS_PROCESSING,\n            )\n            app.logger.exception(\n                \"ims_rollback_master_journal_failed upload_id=%s job_id=%s\",\n                completed.ims_upload_id, job_id,\n            )\n            return False\n\n    IMSProgressStore.write(job_id, percent=42, stage=\"dashboard_snapshot\",'''
if old_begin not in worker:
    raise SystemExit("publication journal insertion point not found")
worker = worker.replace(old_begin, new_begin, 1)
old_late_seal = '''    roster_result = IMSRosterSyncService.sync_latest()\n    app.logger.info(\"ims_roster_sync_success %s\", roster_result)\n    IMSUploadLifecycleService.seal_snapshot_master_state(upload_id=completed.ims_upload_id)\n    summary = json.loads(completed.result_summary or \"{}\")'''
new_late_seal = '''    summary = json.loads(completed.result_summary or \"{}\")'''
if old_late_seal not in worker:
    raise SystemExit("late publication seal block not found")
worker = worker.replace(old_late_seal, new_late_seal, 1)
old_retry = '''def _retryable_publication_job():\n    for job in IMSImportJob.query.filter_by(status=IMSImportJob.STATUS_COMPLETED).order_by(\n        desc(IMSImportJob.completed_at), desc(IMSImportJob.id)\n    ).limit(5):\n        stored = IMSProgressStore.read(job.id) or {}\n        if stored.get(\"stage\") == \"snapshot_retry\":\n            return job\n    return None'''
new_retry = '''def _retryable_publication_job():\n    # Repair only the currently active IMS when an older deployment completed\n    # the business import without sealing/publishing it. Never seal a historical\n    # upload from today's master state.\n    latest_upload = IMSRosterSyncService.latest_completed_upload()\n    if latest_upload is not None:\n        latest_job = (\n            IMSImportJob.query\n            .filter_by(\n                ims_upload_id=latest_upload.id,\n                status=IMSImportJob.STATUS_COMPLETED,\n            )\n            .order_by(desc(IMSImportJob.completed_at), desc(IMSImportJob.id))\n            .first()\n        )\n        if latest_job is not None:\n            try:\n                summary = json.loads(latest_job.result_summary or \"{}\")\n            except (TypeError, ValueError):\n                summary = {}\n            if (\n                not IMSUploadLifecycleService.snapshot_master_state_sealed(\n                    upload_id=latest_upload.id\n                )\n                or not summary.get(\"publication_ready\")\n            ):\n                return latest_job\n\n    for job in IMSImportJob.query.filter_by(status=IMSImportJob.STATUS_COMPLETED).order_by(\n        desc(IMSImportJob.completed_at), desc(IMSImportJob.id)\n    ).limit(5):\n        stored = IMSProgressStore.read(job.id) or {}\n        if stored.get(\"stage\") == \"snapshot_retry\":\n            return job\n    return None'''
if old_retry not in worker:
    raise SystemExit("publication retry block not found")
worker_path.write_text(worker.replace(old_retry, new_retry, 1), encoding="utf-8")


# 4) Pre-login theme toggle: shared auth-only control; existing authenticated navbar is untouched.
partial = Path("app/templates/partials/auth_theme_toggle.html")
partial.write_text('''<button type="button" class="auth-theme-toggle" data-auth-theme-toggle title="Koyu Temaya Geç" aria-label="Koyu Temaya Geç">\n    <i class="bi bi-moon-stars-fill" data-auth-theme-icon aria-hidden="true"></i>\n</button>\n''', encoding="utf-8")
for template_path in ("app/templates/login.html", "app/templates/register.html"):
    replace_once(
        template_path,
        "{% block content %}\n<div class=\"auth-shell",
        "{% block content %}\n{% include \"partials/auth_theme_toggle.html\" %}\n<div class=\"auth-shell",
        "auth theme partial insertion",
    )

layout_path = Path("app/static/js/layout.js")
layout = layout_path.read_text(encoding="utf-8")
layout = layout.replace(
    "    const themeIcon      = document.getElementById('themeIcon');\n",
    "    const themeIcon      = document.getElementById('themeIcon');\n"
    "    const authThemeBtns  = Array.from(document.querySelectorAll('[data-auth-theme-toggle]'));\n",
    1,
)
old_apply = '''        if (themeBtn) {\n            themeBtn.title = theme === 'dark' ? 'Açık Temaya Geç' : 'Koyu Temaya Geç';\n        }\n        window.dispatchEvent'''
new_apply = '''        const themeLabel = theme === 'dark' ? 'Açık Temaya Geç' : 'Koyu Temaya Geç';\n        if (themeBtn) {\n            themeBtn.title = themeLabel;\n        }\n        authThemeBtns.forEach(function (button) {\n            const icon = button.querySelector('[data-auth-theme-icon]');\n            if (icon) {\n                icon.className = theme === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-stars-fill';\n            }\n            button.title = themeLabel;\n            button.setAttribute('aria-label', themeLabel);\n        });\n        window.dispatchEvent'''
if old_apply not in layout:
    raise SystemExit("theme apply block not found")
layout = layout.replace(old_apply, new_apply, 1)
old_bind = "        if (themeBtn) themeBtn.addEventListener('click', toggleTheme);\n"
new_bind = "        if (themeBtn) themeBtn.addEventListener('click', toggleTheme);\n        authThemeBtns.forEach(function (button) { button.addEventListener('click', toggleTheme); });\n"
if old_bind not in layout:
    raise SystemExit("theme binding block not found")
layout_path.write_text(layout.replace(old_bind, new_bind, 1), encoding="utf-8")

css_path = Path("app/static/css/auth-branding.css")
css = css_path.read_text(encoding="utf-8")
css_marker = "/* Pre-login theme toggle */"
if css_marker not in css:
    css += '''\n\n/* Pre-login theme toggle */\n.auth-theme-toggle {\n    position: fixed;\n    top: max(16px, env(safe-area-inset-top));\n    right: max(16px, env(safe-area-inset-right));\n    z-index: 1100;\n    width: 42px;\n    height: 42px;\n    display: inline-flex;\n    align-items: center;\n    justify-content: center;\n    border: 1px solid rgba(11, 78, 162, .18);\n    border-radius: 12px;\n    background: rgba(255, 255, 255, .92);\n    color: #0b4ea2;\n    box-shadow: 0 10px 28px rgba(15, 23, 42, .12);\n    backdrop-filter: blur(8px);\n    -webkit-backdrop-filter: blur(8px);\n    cursor: pointer;\n    transition: transform .16s ease, background-color .16s ease, border-color .16s ease, color .16s ease;\n}\n.auth-theme-toggle:hover {\n    transform: translateY(-1px);\n    background: #fff;\n}\n.auth-theme-toggle:focus-visible {\n    outline: 3px solid rgba(11, 78, 162, .22);\n    outline-offset: 2px;\n}\n.auth-theme-toggle i {\n    font-size: 18px;\n    line-height: 1;\n}\n[data-theme=\"dark\"] .auth-theme-toggle {\n    border-color: rgba(145, 199, 255, .24);\n    background: rgba(21, 34, 56, .94);\n    color: #91c7ff;\n    box-shadow: 0 12px 32px rgba(0, 0, 0, .30);\n}\n[data-theme=\"dark\"] .auth-theme-toggle:hover {\n    background: #1c2d48;\n}\n@media (max-width: 575.98px) {\n    .auth-theme-toggle {\n        top: max(12px, env(safe-area-inset-top));\n        right: max(12px, env(safe-area-inset-right));\n        width: 40px;\n        height: 40px;\n    }\n}\n'''
css_path.write_text(css, encoding="utf-8")


# 5) Narrow source-contract tests only for the requested behavior.
Path("tests/test_ims_rollback_continuity_contract.py").write_text('''from pathlib import Path\n\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef test_rollback_journal_is_sealed_before_snapshot_warmup_and_is_idempotent():\n    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")\n    lifecycle = (ROOT / "app/services/ims_upload_lifecycle_service.py").read_text(encoding="utf-8")\n    publish = worker[worker.index("def _prepare_and_publish"):worker.index("def _retryable_publication_job") ]\n    assert "def snapshot_master_state_sealed" in lifecycle\n    assert "def ensure_snapshot_master_state_sealed" in lifecycle\n    assert publish.index("ensure_snapshot_master_state_sealed") < publish.index("dashboard_result = _warm_dashboard_snapshot")\n    assert "seal_snapshot_master_state(upload_id=completed.ims_upload_id)" not in publish\n\n\ndef test_active_legacy_upload_is_retried_but_historical_upload_is_not_sealed_from_current_state():\n    worker = (ROOT / "ims_import_worker.py").read_text(encoding="utf-8")\n    retry = worker[worker.index("def _retryable_publication_job"):worker.index("def main()") ]\n    assert "latest_upload = IMSRosterSyncService.latest_completed_upload()" in retry\n    assert "ims_upload_id=latest_upload.id" in retry\n    assert "snapshot_master_state_sealed" in retry\n    assert 'summary.get("publication_ready")' in retry\n\n\ndef test_successive_rollbacks_prepare_the_newly_active_legacy_journal():\n    lifecycle = (ROOT / "app/services/ims_upload_lifecycle_service.py").read_text(encoding="utf-8")\n    ui = (ROOT / "app/services/ims_upload_lifecycle_ui.py").read_text(encoding="utf-8")\n    standard = lifecycle[lifecycle.index("def rollback_to_previous"):lifecycle.index("def _invalidate_runtime_caches") ]\n    first_period = ui[ui.index("def _rollback_first_period"):ui.index("def _inject_lifecycle_markup") ]\n    assert "ensure_snapshot_master_state_sealed(upload_id=previous.id)" in standard\n    assert "ensure_snapshot_master_state_sealed" in first_period\n    assert "upload_id=previous_global.id" in first_period\n''', encoding="utf-8")

Path("tests/test_auth_theme_toggle_contract.py").write_text('''from pathlib import Path\n\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef test_login_and_register_expose_prelogin_theme_control_only_through_shared_partial():\n    login = (ROOT / "app/templates/login.html").read_text(encoding="utf-8")\n    register = (ROOT / "app/templates/register.html").read_text(encoding="utf-8")\n    partial = (ROOT / "app/templates/partials/auth_theme_toggle.html").read_text(encoding="utf-8")\n    for template in (login, register):\n        assert '{% include "partials/auth_theme_toggle.html" %}' in template\n    assert "data-auth-theme-toggle" in partial\n    assert "data-auth-theme-icon" in partial\n    assert "themeToggleBtn" not in partial\n\n\ndef test_prelogin_theme_uses_existing_persisted_theme_engine_and_top_right_auth_css():\n    layout = (ROOT / "app/static/js/layout.js").read_text(encoding="utf-8")\n    css = (ROOT / "app/static/css/auth-branding.css").read_text(encoding="utf-8")\n    assert "const THEME_KEY = 'ims-theme'" in layout\n    assert "authThemeBtns" in layout\n    assert "localStorage.setItem(THEME_KEY, next)" in layout\n    assert "data-auth-theme-icon" in layout\n    assert "/* Pre-login theme toggle */" in css\n    assert "position: fixed" in css\n    assert "right: max(16px, env(safe-area-inset-right))" in css\n    assert '[data-theme="dark"] .auth-theme-toggle' in css\n''', encoding="utf-8")

print("PR 755 scoped patch prepared")
