"""Manager-facing compact IMS import result reporting.

The complete parser ledger stays in runtime/audit logs; this service persists a
small structured summary in the existing ImportAuditLog.notes field and surfaces
it once on the IMS Centre after an upload. No schema, dashboard or prime data model
changes are required.
"""
from __future__ import annotations

import json
import time
from datetime import datetime

from flask import flash, request, session

from app.extensions import db
from app.models import (
    CompetitionData,
    ImportAuditLog,
    IMSFact,
    IMSRawData,
    IMSSummary,
    Representative,
    Target,
)

REPORT_MARKER = "IMS_IMPORT_REPORT_V1"
BLOCKING_KEYS = (
    "unclassified_sheet",
    "unclassified_master_cell",
    "unresolved_representative",
    "unresolved_product",
    "invalid_metric",
    "invalid_metric_records",
    "row_error",
    "rows_error",
    "conflicting_match",
    "duplicate_conflict",
)


def _stat(stats, *names):
    for name in names:
        value = stats.get(name)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return value
    return 0


def _period_counts(service):
    upload = service.upload
    if upload is None:
        return {}
    facts = IMSFact.query.filter_by(upload_id=upload.id).count()
    summary = IMSSummary.query.filter_by(year=upload.year, month=upload.month).count()
    targets = Target.query.filter_by(year=upload.year, month=upload.month).count()
    competition = CompetitionData.query.filter_by(upload_id=upload.id).count()
    spread = IMSRawData.query.filter_by(
        upload_id=upload.id, sheet_type="official_brick_spread_master"
    ).count()
    aggregates = IMSRawData.query.filter(
        IMSRawData.upload_id == upload.id,
        IMSRawData.sheet_type.in_(("official_target_aggregate", "official_actual_aggregate")),
    ).count()
    reps = db.session.query(IMSFact.representative_id).filter_by(upload_id=upload.id).distinct().count()
    products = db.session.query(IMSFact.product_id).filter_by(upload_id=upload.id).distinct().count()
    vacancy_reps = (
        db.session.query(Representative.id)
        .join(IMSFact, IMSFact.representative_id == Representative.id)
        .filter(IMSFact.upload_id == upload.id, Representative.rep_code.like("UNASSIGNED%"))
        .distinct()
        .count()
    )
    region_codes = {
        str(row[0])
        for row in db.session.query(IMSRawData.territory)
        .filter(
            IMSRawData.upload_id == upload.id,
            IMSRawData.sheet_type.in_(("official_target_aggregate", "official_actual_aggregate")),
            IMSRawData.territory.isnot(None),
            IMSRawData.territory != "NATIONAL",
        )
        .distinct()
        .all()
        if row[0]
    }
    return {
        "facts": facts,
        "summary": summary,
        "targets": targets,
        "competition": competition,
        "official_brick_spread": spread,
        "official_aggregates": aggregates,
        "representatives": reps,
        "vacancies": vacancy_reps,
        "products": products,
        "regions": len(region_codes),
    }


def build_import_result_summary(service, *, success=None):
    stats = service.statistics
    upload = service.upload
    if success is None:
        success = not bool(service.errors)
    blocking = {key: _stat(stats, key) for key in BLOCKING_KEYS}
    unresolved_rep = max(
        blocking.get("unresolved_representative", 0),
        _stat(stats, "unresolved_representative_rows", "unmatched_representatives"),
    )
    unresolved_product = max(
        blocking.get("unresolved_product", 0),
        _stat(stats, "unmatched_products"),
    )
    invalid = max(
        blocking.get("invalid_metric", 0),
        blocking.get("invalid_metric_records", 0),
    )
    row_error = max(
        blocking.get("row_error", 0),
        blocking.get("rows_error", 0),
    )
    critical = {
        "unclassified_sheet": blocking.get("unclassified_sheet", 0),
        "unclassified_master_cell": blocking.get("unclassified_master_cell", 0),
        "unresolved_representative": unresolved_rep,
        "unresolved_product": unresolved_product,
        "invalid_metric": invalid,
        "row_error": row_error,
        "conflicting_match": blocking.get("conflicting_match", 0),
        "duplicate_conflict": blocking.get("duplicate_conflict", 0),
    }
    final_result = "PASS" if success and not service.errors and not any(critical.values()) else "FAIL"
    manifest = getattr(service, "workbook_manifest", []) or []
    counts = _period_counts(service)
    summary = {
        "marker": REPORT_MARKER,
        "final_result": final_result,
        "upload_id": upload.id if upload else None,
        "file_name": upload.file_name if upload else None,
        "period": {
            "year": upload.year if upload else None,
            "month": upload.month if upload else None,
            "week_number": upload.week_number if upload else None,
        },
        "sheets": {
            "verified": int(stats.get("manifest_verified_sheets", 0) or 0),
            "total": int(stats.get("manifest_sheet_count", len(manifest)) or len(manifest)),
        },
        "source": {
            "records": int(stats.get("source_metric_records", 0) or 0),
            "stored": int(stats.get("stored_source_records", 0) or 0),
            "zero_metrics": int(stats.get("zero_metric_records", 0) or 0),
            "meaningful_cells": int(stats.get("manifest_meaningful_cells", 0) or 0),
        },
        "matches": {
            "representatives": counts.get("representatives", 0),
            "vacancies": counts.get("vacancies", 0),
            "products": counts.get("products", 0),
            "auto_repaired": int(stats.get("auto_repaired", 0) or 0),
        },
        "counts": counts,
        "critical": critical,
        "national_region": getattr(service, "national_region_reconciliation", None),
        "previous_ims_delta": getattr(service, "previous_ims_delta", None),
        "semantic_relationship_count": int(stats.get("semantic_relationship_count", 0) or 0),
        "warnings_count": len(service.warnings),
        "errors_count": len(service.errors),
        "generated_at": datetime.utcnow().isoformat(),
    }
    return summary


def encode_report(summary):
    return json.dumps(summary, ensure_ascii=False, sort_keys=True, default=str)


def decode_report(notes):
    if not notes:
        return None
    try:
        parsed = json.loads(notes)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.get("marker") == REPORT_MARKER else None


def latest_import_report():
    audit = ImportAuditLog.query.order_by(ImportAuditLog.uploaded_at.desc(), ImportAuditLog.id.desc()).first()
    return decode_report(audit.notes) if audit else None


def _manager_message(report):
    counts = report.get("counts", {})
    source = report.get("source", {})
    sheets = report.get("sheets", {})
    critical = report.get("critical", {})
    delta = report.get("previous_ims_delta") or {}
    problem_total = sum(int(value or 0) for value in critical.values())
    headline = (
        "IMS eksiksiz ve hatasız içe aktarıldı"
        if report.get("final_result") == "PASS" and problem_total == 0
        else "IMS içe aktarımı doğrulama sorunları nedeniyle yayınlanmadı"
    )
    return (
        f"{headline}. "
        f"Sayfa {sheets.get('verified', 0)}/{sheets.get('total', 0)}; "
        f"kaynak/kayıt {source.get('records', 0)}/{source.get('stored', 0)}; "
        f"fact {counts.get('facts', 0)}, summary {counts.get('summary', 0)}, hedef {counts.get('targets', 0)}, "
        f"rekabet {counts.get('competition', 0)}, resmi brick {counts.get('official_brick_spread', 0)}; "
        f"temsilci {counts.get('representatives', 0)}, vacancy {counts.get('vacancies', 0)}, ürün {counts.get('products', 0)}, "
        f"bölge {counts.get('regions', 0)}; auto-repair {report.get('matches', {}).get('auto_repaired', 0)}; "
        f"unresolved {critical.get('unresolved_representative', 0) + critical.get('unresolved_product', 0)}, "
        f"invalid {critical.get('invalid_metric', 0)}, conflict {critical.get('conflicting_match', 0) + critical.get('duplicate_conflict', 0)}; "
        f"önceki IMS delta: satış {delta.get('sales_changed', 0)}, hedef {delta.get('targets_changed', 0)}, "
        f"bölge/kadro {delta.get('region_cadre_changed', 0)}, brick {delta.get('brick_spread_changed', 0)}, rekabet {delta.get('competition_changed', 0)}."
    )


def register_import_result_flash(app):
    """Surface each persisted manager report once per user session on IMS Centre."""
    @app.before_request
    def _surface_latest_import_report():
        if request.endpoint != "ims.index":
            return None
        report = latest_import_report()
        if not report or report.get("upload_id") is None:
            return None
        token = f"{report.get('upload_id')}:{report.get('final_result')}:{report.get('generated_at')}"
        if session.get("_ims_report_seen") == token:
            return None
        flash(
            _manager_message(report),
            "success" if report.get("final_result") == "PASS" else "danger",
        )
        session["_ims_report_seen"] = token
        return None


def install_import_result_reporting():
    from app.services.ims_import_service import IMSImportService

    if getattr(IMSImportService, "_manager_import_reporting_installed", False):
        return

    original_write = IMSImportService.write_audit_log
    original_failure = IMSImportService._persist_failure

    def write_audit_with_report(self, year, month, week_number, success):
        original_write(self, year, month, week_number, success)
        summary = build_import_result_summary(self, success=success)
        for obj in reversed(list(db.session.new)):
            if isinstance(obj, ImportAuditLog) and obj.upload_id == self.upload.id:
                obj.notes = encode_report(summary)
                break
        self.import_result_summary = summary

    def persist_failure_with_report(self, year, month, week_number=None):
        original_failure(self, year, month, week_number=week_number)
        summary = build_import_result_summary(self, success=False)
        audit = ImportAuditLog(
            upload_id=self.upload.id,
            year=year,
            month=month,
            week_number=week_number,
            uploaded_by=self.uploaded_by,
            rows_inserted=0,
            rows_updated=0,
            rows_skipped=_stat(self.statistics, "skipped_records"),
            rows_unmatched=(
                _stat(self.statistics, "unmatched_representatives")
                + _stat(self.statistics, "unmatched_products")
                + _stat(self.statistics, "unmatched_regions")
                + _stat(self.statistics, "unmatched_provinces")
            ),
            rows_error=max(1, _stat(self.statistics, "rows_error") + len(self.errors)),
            queued_for_manual=_stat(self.statistics, "queued_for_manual"),
            processing_time=round(time.monotonic() - self.started, 2),
            status="FAILED",
            notes=encode_report(summary),
        )
        db.session.add(audit)
        db.session.commit()
        self.import_result_summary = summary

    IMSImportService.write_audit_log = write_audit_with_report
    IMSImportService._persist_failure = persist_failure_with_report
    IMSImportService._manager_import_reporting_installed = True
