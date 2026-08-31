"""Safe in-place retry for failed IMS imports using preserved source files."""
from __future__ import annotations

import hashlib
import shutil
from datetime import datetime
from pathlib import Path

from flask import current_app, flash, redirect, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import IMSImportJob, IMSUpload
from app.services.ims_upload_lifecycle_service import IMSUploadLifecycleService


def _active_job():
    return (
        IMSImportJob.query
        .filter(IMSImportJob.status.in_((IMSImportJob.STATUS_QUEUED, IMSImportJob.STATUS_PROCESSING)))
        .order_by(IMSImportJob.queued_at, IMSImportJob.id)
        .first()
    )


def _failed_source_for_job(job: IMSImportJob) -> Path | None:
    root = IMSUploadLifecycleService._archive_root()
    for suffix in (".xlsx", ".xls"):
        candidate = root / f"failed-job-{int(job.id)}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install_ims_failed_retry_ui(app):
    endpoint = "ims_failed_retry"
    if endpoint in app.view_functions:
        return

    @app.post("/ims/uploads/<int:upload_id>/retry", endpoint=endpoint)
    @login_required
    def retry_failed_ims(upload_id):
        upload = db.session.get(IMSUpload, upload_id)
        if upload is None:
            flash("IMS yükleme kaydı bulunamadı.", "warning")
            return redirect(url_for("ims.index") + "#ims-history")
        if upload.status not in ("FAILED", "Hata"):
            flash("Yalnızca başarısız IMS yüklemeleri yeniden işlenebilir.", "warning")
            return redirect(url_for("ims.index") + "#ims-history")
        if _active_job() is not None:
            flash("Başka bir IMS aktarımı devam ediyor. Tamamlandıktan sonra tekrar deneyin.", "warning")
            return redirect(url_for("ims.index") + "#ims-history")

        job = (
            IMSImportJob.query
            .filter_by(ims_upload_id=upload.id, status=IMSImportJob.STATUS_FAILED)
            .order_by(IMSImportJob.id.desc())
            .first()
        )
        if job is None:
            flash("Bu başarısız IMS için yeniden işleme kuyruğu kaydı bulunamadı.", "warning")
            return redirect(url_for("ims.index") + "#ims-history")

        source = _failed_source_for_job(job)
        if source is None:
            flash(
                "Bu eski başarısız IMS'in güvenli kaynak kopyası önceki sürüm tarafından saklanmamış. "
                "Bu dosyayı yalnızca bir kez yeniden seçip yükleyin; bundan sonraki hatalarda Tekrar Dene kullanılabilecek.",
                "warning",
            )
            return redirect(url_for("ims.index") + "#ims-history")
        if _sha256(source) != str(job.source_hash or ""):
            flash("Güvenli IMS kaynak dosyasının SHA-256 değeri audit kaydıyla eşleşmiyor; yeniden işleme reddedildi.", "danger")
            return redirect(url_for("ims.index") + "#ims-history")

        staging = Path(current_app.config["UPLOAD_FOLDER"]) / "ims_queue" / job.stored_file_name
        staging.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source, staging)
            if _sha256(staging) != str(job.source_hash or ""):
                raise RuntimeError("Staging SHA-256 doğrulaması başarısız.")

            now = datetime.utcnow()
            upload.status = "PROCESSING"
            upload.error_message = None
            upload.reconciliation_status = "NOT_AVAILABLE"
            upload.uploaded_by = current_user.full_name
            upload.completed_at = None
            job.status = IMSImportJob.STATUS_QUEUED
            job.uploaded_by = current_user.full_name
            job.started_at = None
            job.completed_at = None
            job.heartbeat_at = None
            job.error_message = None
            job.result_summary = None
            job.queued_at = now
            db.session.commit()
        except Exception:
            db.session.rollback()
            staging.unlink(missing_ok=True)
            current_app.logger.exception("ims_failed_retry_enqueue_failed upload_id=%s job_id=%s", upload_id, job.id)
            flash("IMS yeniden işleme kuyruğuna alınamadı; mevcut veriler korunmuştur.", "danger")
            return redirect(url_for("ims.index") + "#ims-history")

        flash("Aynı güvenli IMS dosyası yeniden doğrulama kuyruğuna alındı.", "success")
        return redirect(url_for("ims.index") + "#ims-history")
