from flask import Blueprint
from flask import current_app
from flask import flash
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for
import hashlib
from pathlib import Path
from uuid import uuid4

from flask_login import current_user
from flask_login import login_required
from sqlalchemy import tuple_

from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import IMSUpload
from app.models import IMSSummary
from app.models import Product
from app.models import ProductionResultUpload
from app.models import Representative
from app.models import Target

from app.services.dashboard_service import (
    DashboardService
)
from app.services.ims_import_service import (
    IMSImportService
)
from app.services.import_coordinator import (
    ImportBusyError,
    ImportCoordinator,
)
from app.services.official_brick_spread_service import OfficialBrickSpreadService
from app.services.period_service import PeriodService
from app.services.production_result_import_service import (
    ProductionResultImportService,
    ProductionWorkbookValidationError,
)


ims_bp = Blueprint(

    "ims",

    __name__,

    url_prefix="/ims"

)


def _manager_reports(uploads):
    """Build manager completeness reports with a fixed number of queries.

    Target and summary data are period-scoped, so recalculating the same six
    queries for every historical upload is both redundant and increasingly
    expensive.  Fetch every visible period once and retain the existing report
    semantics for each upload.
    """
    if not uploads:
        return {}

    periods = {(item.year, item.month) for item in uploads}
    target_rows = db.session.query(
        Target.year,
        Target.month,
        Target.representative_id,
        Target.product_id,
    ).filter(tuple_(Target.year, Target.month).in_(periods)).all()
    summary_rows = db.session.query(
        IMSSummary.year,
        IMSSummary.month,
        IMSSummary.representative_id,
        IMSSummary.product_id,
    ).filter(tuple_(IMSSummary.year, IMSSummary.month).in_(periods)).all()

    target_keys_by_period = {period: set() for period in periods}
    summary_keys_by_period = {period: set() for period in periods}
    for year, month, representative_id, product_id in target_rows:
        target_keys_by_period[(year, month)].add((representative_id, product_id))
    for year, month, representative_id, product_id in summary_rows:
        summary_keys_by_period[(year, month)].add((representative_id, product_id))

    active_representatives = Representative.query.filter(
        Representative.active.is_(True)
    ).all()
    active_real_representatives = {
        item.id: item
        for item in active_representatives
        if not str(item.rep_code or "").upper().startswith("UNASSIGNED")
    }
    active_real_ids = set(active_real_representatives)
    active_regions = {
        str(item.region).strip()
        for item in active_representatives
        if item.region and str(item.region).strip()
    }
    active_product_ids = {
        item.id for item in Product.query.filter_by(is_active=True).all()
    }

    reports = {}
    for upload in uploads:
        period = (upload.year, upload.month)
        target_keys = target_keys_by_period.get(period, set())
        summary_keys = summary_keys_by_period.get(period, set())
        target_rep_ids = {
            representative_id
            for representative_id, _ in target_keys
            if representative_id
        }
        target_product_ids = {product_id for _, product_id in target_keys if product_id}
        represented_real_ids = target_rep_ids & active_real_ids
        represented_regions = {
            str(active_real_representatives[item_id].region).strip()
            for item_id in represented_real_ids
            if active_real_representatives[item_id].region
        }
        represented_active_products = target_product_ids & active_product_ids

        reconciled = upload.status == "COMPLETED" and upload.reconciliation_status == "PASSED"
        source_complete = (
            int(upload.source_record_count or 0) > 0
            and int(upload.source_record_count or 0)
            == int(upload.stored_source_record_count or 0)
            and int(upload.invalid_metric_count or 0) == 0
        )
        representative_complete = bool(active_real_ids) and represented_real_ids == active_real_ids
        region_complete = bool(active_regions) and represented_regions == active_regions
        product_complete = bool(active_product_ids) and represented_active_products == active_product_ids
        calculation_complete = bool(target_keys) and target_keys.issubset(summary_keys)
        total_tl_complete = reconciled and source_complete and calculation_complete
        realization_complete = total_tl_complete and len(target_keys) == len(summary_keys)

        checks = [
            representative_complete,
            region_complete,
            product_complete,
            total_tl_complete,
            realization_complete,
        ]
        reports[upload.id] = {
            "overall": all(checks),
            "representative_count": len(represented_real_ids),
            "representatives_ok": representative_complete,
            "region_count": len(represented_regions),
            "regions_ok": region_complete,
            "product_count": len(represented_active_products),
            "products_ok": product_complete,
            "total_tl_ok": total_tl_complete,
            "realization_ok": realization_complete,
            "sheet_count": int(upload.sheet_count or 0),
            "source_count": int(upload.source_record_count or 0),
            "stored_count": int(upload.stored_source_record_count or 0),
        }
    return reports


def _manager_report(upload):
    """Backward-compatible single-upload report entry point."""
    return _manager_reports([upload])[upload.id]


@ims_bp.route(

    "/"

)
@login_required
def index():
    history_page = max(request.args.get("history_page", 1, type=int) or 1, 1)
    history_query = (request.args.get("history_q") or "").strip()[:100]
    history_status = (request.args.get("history_status") or "").strip()

    upload_query = IMSUpload.query
    if history_query:
        upload_query = upload_query.filter(IMSUpload.file_name.ilike(f"%{history_query}%"))
    status_groups = {
        "completed": ("COMPLETED", "Hazır"),
        "processing": ("PROCESSING", "İşleniyor"),
        "failed": ("FAILED", "Hata"),
    }
    if history_status in status_groups:
        upload_query = upload_query.filter(IMSUpload.status.in_(status_groups[history_status]))

    upload_pagination = upload_query.order_by(
        IMSUpload.uploaded_at.desc(), IMSUpload.id.desc()
    ).paginate(page=history_page, per_page=25, error_out=False)
    uploads = upload_pagination.items
    latest_upload = IMSUpload.query.order_by(
        IMSUpload.uploaded_at.desc(), IMSUpload.id.desc()
    ).first()
    total_uploads = IMSUpload.query.count()

    production_uploads = ProductionResultUpload.query.order_by(
        ProductionResultUpload.uploaded_at.desc()
    ).all()

    ims_period = PeriodService.get_active_period()
    import_status = ImportCoordinator.status()
    manager_reports = _manager_reports(uploads)

    # TEMP DEBUG
    dashboard = {}
    # dashboard = {}

    return render_template(

        "ims.html",

        uploads=uploads,
        latest_upload=latest_upload,
        total_uploads=total_uploads,
        upload_pagination=upload_pagination,
        history_query=history_query,
        history_status=history_status,

        production_uploads=production_uploads,

        dashboard=dashboard,

        ims_period=ims_period,

        import_status=import_status,

        manager_reports=manager_reports,

    )


@ims_bp.route("/production-upload", methods=["POST"])
@login_required
def production_upload():
    """Validate and apply a production workbook without changing IMS source data."""
    file = request.files.get("file")
    if file is None or not file.filename:
        flash("Lütfen bir üretim sonucu Excel dosyası seçiniz.", "warning")
        return redirect(url_for("ims.index") + "#production-results")

    original_name = secure_filename(file.filename)
    extension = Path(original_name).suffix.lower()
    if not original_name or extension not in {".xlsx", ".xls"}:
        flash("Üretim sonucu için yalnızca .xlsx veya .xls dosyası yüklenebilir.", "danger")
        return redirect(url_for("ims.index") + "#production-results")

    try:
        year = int(request.form.get("year", ""))
        month = int(request.form.get("month", ""))
        production_stage = int(request.form.get("production_stage", ""))
        if year < 2020 or year > 2100 or month not in range(1, 13) or production_stage not in {1, 2}:
            raise ValueError
    except (TypeError, ValueError):
        flash("Dönem veya üretim aşaması geçersiz.", "danger")
        return redirect(url_for("ims.index") + "#production-results")

    payload = file.read()
    source_hash = hashlib.sha256(payload).hexdigest()
    existing = ProductionResultUpload.query.filter_by(source_hash=source_hash).first()
    if existing:
        flash(
            f"Bu üretim dosyası daha önce {existing.year}/{existing.month:02d} dönemi için yüklenmiş.",
            "warning",
        )
        return redirect(url_for("ims.index") + "#production-results")

    production_folder = current_app.config["UPLOAD_FOLDER"] / "production_results"
    production_folder.mkdir(parents=True, exist_ok=True)
    stored_file_name = f"{year}-{month:02d}-u{production_stage}-{uuid4().hex}{extension}"
    stored_path = production_folder / stored_file_name

    try:
        stored_path.write_bytes(payload)
        upload = ProductionResultUpload(
            file_name=original_name,
            stored_file_name=stored_file_name,
            source_hash=source_hash,
            year=year,
            month=month,
            production_stage=production_stage,
            status=ProductionResultUpload.STATUS_PENDING_VALIDATION,
            uploaded_by=current_user.full_name,
            warning_message=(
                "Dosya güvenli alana alındı. Şablon doğrulaması tamamlanana kadar mevcut IMS, "
                "realizasyon ve prim hesaplarına uygulanmayacaktır."
            ),
        )
        db.session.add(upload)
        db.session.flush()
        report = ProductionResultImportService(stored_path).parse()
        ProductionResultImportService.apply(upload, report)
        db.session.commit()
    except ProductionWorkbookValidationError as exc:
        db.session.rollback()
        # Preserve rejected source evidence and its reason without applying any result.
        upload = ProductionResultUpload(
            file_name=original_name, stored_file_name=stored_file_name, source_hash=source_hash,
            year=year, month=month, production_stage=production_stage,
            status=ProductionResultUpload.STATUS_FAILED, uploaded_by=current_user.full_name,
            error_message=str(exc),
        )
        db.session.add(upload)
        db.session.commit()
        flash(f"Üretim dosyası uygulanmadı: {exc}", "danger")
        return redirect(url_for("ims.index") + "#production-results")
    except Exception:
        db.session.rollback()
        stored_path.unlink(missing_ok=True)
        current_app.logger.exception("production_result_staging_failed")
        flash("Üretim sonucu dosyası güvenli alana kaydedilemedi.", "danger")
        return redirect(url_for("ims.index") + "#production-results")

    flash(
        f"{production_stage}. üretim dosyası doğrulandı ve uygulandı. IMS hedefleri ve kaynak satış verileri korunmuştur.",
        "success",
    )
    return redirect(url_for("ims.index") + "#production-results")


@ims_bp.route(

    "/upload",

    methods=["POST"]

)
@login_required
def upload():

    file = request.files.get(

        "file"

    )

    if file is None or file.filename == "":

        flash(

            "Lütfen bir IMS dosyası seçiniz.",

            "warning"

        )

        return redirect(

            url_for(

                "ims.index"

            )

        )

    filename = secure_filename(file.filename)
    extension = Path(filename).suffix.lower()
    if not filename or extension not in {".xlsx", ".xls"}:
        flash("IMS için yalnızca .xlsx veya .xls dosyası yüklenebilir.", "danger")
        return redirect(url_for("ims.index"))

    try:
        year = int(request.form.get("year", ""))
        month = int(request.form.get("month", ""))
        if year < 2020 or year > 2100 or month not in range(1, 13):
            raise ValueError
    except (TypeError, ValueError):
        flash("IMS dönemi geçersiz. Yıl ve ay bilgisini kontrol edin.", "danger")
        return redirect(url_for("ims.index"))

    uploaded_by = current_user.full_name
    upload_path = current_app.config["UPLOAD_FOLDER"] / filename

    try:
        with ImportCoordinator.acquire(
            uploaded_by=uploaded_by,
            file_name=filename,
            wait_seconds=current_app.config.get("IMS_IMPORT_LOCK_WAIT_SECONDS", 2),
        ):
            # Save only after the cross-process lock is ours.  Two managers can
            # therefore never overwrite/process the same upload path at once.
            file.save(upload_path)

            service = IMSImportService(
                file_path=upload_path,
                uploaded_by=uploaded_by,
            )

            result = service.run(
                year=year,
                month=month,
                clear_before_import=False,
            )

            # Satış Brick Yayılımı is an official aggregate master source.  It
            # intentionally lives outside sales FACT/SUMMARY calculations, but
            # is persisted before the import lock is released so another
            # manager can never observe a half-integrated workbook.
            if result["success"]:
                spread_result = OfficialBrickSpreadService.persist(
                    file_path=upload_path,
                    upload_id=result["upload_id"],
                    year=year,
                    month=month,
                )
                result["statistics"]["official_brick_spread_records"] = spread_result["records"]
                result["statistics"]["official_brick_spread_representatives"] = spread_result["representatives"]

                # The generic parser previously reported this specialized
                # master sheet as skipped.  Once the dedicated parser succeeds,
                # remove only that obsolete warning and persist the corrected
                # audit state.
                result["warnings"] = [
                    warning
                    for warning in result.get("warnings", [])
                    if "SATIS BRICK YAYILIMI" not in OfficialBrickSpreadService._normalize(warning)
                ]
                upload_record = db.session.get(IMSUpload, result["upload_id"])
                if upload_record is not None:
                    upload_record.warning_message = "\n".join(result["warnings"]) or None
                db.session.commit()

        if result["success"]:

            flash(

                (
                    f"{filename} başarıyla içe aktarıldı. Veri bütünlüğü doğrulandı: "
                    f"{result['statistics'].get('stored_source_records', 0)}/"
                    f"{result['statistics'].get('source_metric_records', 0)} kayıt; "
                    f"{result['statistics'].get('zero_metric_records', 0)} sıfır satış kaydı korundu; "
                    f"{result['statistics'].get('official_brick_spread_records', 0)} resmi brick yayılım kaydı saklandı."
                ),

                "success"

            )

            if result.get(

                "warnings"

            ):

                flash(

                    f"{len(result['warnings'])} uyarı oluştu.",

                    "warning"

                )

        else:

            current_app.logger.error(
                "ims_upload_failed file=%s errors=%s",
                filename,
                result.get("errors", []),
            )
            flash(
                "IMS dosyası doğrulama sırasında tamamlanamadı. Mevcut dönem verileri korunmuştur; sistem yöneticisi logları inceleyebilir.",
                "danger",
            )

    except ImportBusyError as exc:
        current = exc.metadata
        owner = current.get("uploaded_by")
        started_at = current.get("started_at")
        current_app.logger.warning(
            "ims_upload_rejected_busy requested_by=%s file=%s active=%s",
            uploaded_by,
            filename,
            current,
        )
        detail = ""
        if owner:
            detail = f" Aktif işlem: {owner}"
            active_file = current.get("file_name")
            if active_file:
                detail += f" · {active_file}"
            if started_at:
                detail += f" · başlangıç {started_at}"
            detail += ". Sayfayı yenileyerek durumu kontrol edin; dosyayı tekrar göndermeyin."
        flash(
            "Başka bir IMS dosyası şu anda güvenli biçimde işleniyor. Lütfen mevcut işlem tamamlandıktan sonra tekrar deneyin." + detail,
            "warning",
        )
    except Exception:
        db.session.rollback()
        current_app.logger.exception("ims_upload_unexpected_failure file=%s", filename)
        flash(
            "IMS yükleme sırasında beklenmeyen bir teknik sorun oluştu. Mevcut veriler korunmuştur; tekrar deneyebilirsiniz.",
            "danger",
        )

    return redirect(

        url_for(

            "ims.index"

        )

    )
