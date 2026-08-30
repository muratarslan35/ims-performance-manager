import hashlib
from pathlib import Path

from flask import current_app, flash, redirect, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import IMSImportJob, ProductionResultUpload
from app.services.production_result_import_service import (
    ProductionResultImportService,
    ProductionWorkbookValidationError,
)


_RETRY_BADGE = '<span class="badge bg-danger">Hatalı</span>'


def _stored_source_path(upload):
    return (
        Path(current_app.config["UPLOAD_FOLDER"])
        / "production_results"
        / str(upload.stored_file_name or "")
    )


def _source_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _active_ims_job():
    return (
        IMSImportJob.query
        .filter(
            IMSImportJob.status.in_(
                (IMSImportJob.STATUS_QUEUED, IMSImportJob.STATUS_PROCESSING)
            )
        )
        .order_by(IMSImportJob.queued_at, IMSImportJob.id)
        .first()
    )


def install_production_result_retry_ui(app):
    """Install safe, in-place retry for failed production-result audit rows."""

    endpoint = "production_result_retry"
    if endpoint not in app.view_functions:

        @app.post(
            "/ims/production-uploads/<int:upload_id>/retry",
            endpoint=endpoint,
        )
        @login_required
        def retry_production_result(upload_id):
            upload = db.session.get(ProductionResultUpload, upload_id)
            if upload is None:
                flash("Üretim sonucu kaydı bulunamadı.", "warning")
                return redirect(url_for("ims.index") + "#production-results")

            if upload.status != ProductionResultUpload.STATUS_FAILED:
                flash("Yalnızca hatalı üretim sonuçları yeniden işlenebilir.", "warning")
                return redirect(url_for("ims.index") + "#production-results")

            if _active_ims_job() is not None:
                flash(
                    "IMS aktarımı devam ederken üretim sonucu yeniden işlenmez. "
                    "IMS tamamlandıktan sonra tekrar deneyin.",
                    "warning",
                )
                return redirect(url_for("ims.index") + "#production-results")

            stored_path = _stored_source_path(upload)
            try:
                if not upload.stored_file_name or not stored_path.is_file():
                    raise ProductionWorkbookValidationError(
                        "Güvenli alandaki üretim kaynak dosyası bulunamadı."
                    )
                if _source_hash(stored_path) != upload.source_hash:
                    raise ProductionWorkbookValidationError(
                        "Güvenli alandaki kaynak dosyanın SHA-256 değeri audit kaydıyla eşleşmiyor."
                    )

                report = ProductionResultImportService(
                    stored_path,
                    upload.year,
                    upload.month,
                    production_stage=upload.production_stage,
                ).parse()
                ProductionResultImportService.apply(upload, report)
                upload.error_message = None
                upload.warning_message = None
                upload.uploaded_by = current_user.full_name
                db.session.commit()
            except ProductionWorkbookValidationError as exc:
                db.session.rollback()
                failed = db.session.get(ProductionResultUpload, upload_id)
                if failed is not None:
                    failed.status = ProductionResultUpload.STATUS_FAILED
                    failed.error_message = str(exc)
                    failed.warning_message = None
                    failed.uploaded_by = current_user.full_name
                    db.session.commit()
                flash(f"Üretim sonucu yine uygulanamadı: {exc}", "danger")
                return redirect(url_for("ims.index") + "#production-results")
            except Exception:
                db.session.rollback()
                failed = db.session.get(ProductionResultUpload, upload_id)
                if failed is not None:
                    failed.status = ProductionResultUpload.STATUS_FAILED
                    failed.error_message = "Yeniden işleme sırasında beklenmeyen sistem hatası oluştu."
                    failed.warning_message = None
                    db.session.commit()
                current_app.logger.exception(
                    "production_result_retry_failed upload_id=%s", upload_id
                )
                flash(
                    "Üretim sonucu yeniden işlenemedi. Mevcut veriler korunmuştur.",
                    "danger",
                )
                return redirect(url_for("ims.index") + "#production-results")

            flash(
                f"{upload.production_stage}. üretim sonucu aynı güvenli dosyadan yeniden "
                "doğrulandı ve uygulandı.",
                "success",
            )
            return redirect(url_for("ims.index") + "#production-results")

    if not app.extensions.get("production_result_retry_ui_installed"):

        @app.after_request
        def inject_production_retry_controls(response):
            if (
                request.method != "GET"
                or request.path.rstrip("/") != "/ims"
                or response.status_code != 200
                or not response.mimetype.startswith("text/html")
            ):
                return response

            failed_uploads = (
                ProductionResultUpload.query
                .filter_by(status=ProductionResultUpload.STATUS_FAILED)
                .order_by(ProductionResultUpload.uploaded_at.desc())
                .all()
            )
            if not failed_uploads:
                return response

            html = response.get_data(as_text=True)
            for upload in failed_uploads:
                if _RETRY_BADGE not in html:
                    break
                retry_url = url_for(endpoint, upload_id=upload.id)
                control = (
                    _RETRY_BADGE
                    + '<form method="post" action="'
                    + retry_url
                    + '" class="d-inline ms-2">'
                    + '<button type="submit" class="btn btn-sm btn-outline-danger py-0 px-2" '
                    + 'title="Aynı güvenli dosyayı yeniden doğrula" '
                    + 'onclick="this.disabled=true;this.innerHTML=\'İşleniyor...\';this.form.submit();">'
                    + '<i class="bi bi-arrow-clockwise me-1"></i>Tekrar Dene</button></form>'
                )
                html = html.replace(_RETRY_BADGE, control, 1)
            response.set_data(html)
            return response

        app.extensions["production_result_retry_ui_installed"] = True
