"""Align manager-facing IMS completeness checks with the canonical import gate.

The import result audit is the single source of truth for whether an IMS upload
was publishable.  This adapter replaces the legacy period-cardinality check
that incorrectly required every target row to have a summary row.
"""
from __future__ import annotations

from app.extensions import db
from app.models import ImportAuditLog
from app.services.import_result_report import decode_report


def _latest_reports_for_uploads(uploads):
    ids = [item.id for item in uploads if getattr(item, "id", None) is not None]
    if not ids:
        return {}
    rows = (
        ImportAuditLog.query
        .filter(ImportAuditLog.upload_id.in_(ids))
        .order_by(ImportAuditLog.upload_id, ImportAuditLog.id.desc())
        .all()
    )
    reports = {}
    for audit in rows:
        if audit.upload_id in reports:
            continue
        parsed = decode_report(audit.notes)
        if parsed:
            reports[audit.upload_id] = parsed
    return reports


def canonical_manager_reports(uploads):
    """Build UI reports from the same persisted audit that approved publication."""
    if not uploads:
        return {}

    canonical = _latest_reports_for_uploads(uploads)
    reports = {}
    for upload in uploads:
        report = canonical.get(upload.id) or {}
        counts = report.get("counts") or {}
        source = report.get("source") or {}
        critical = report.get("critical") or {}

        final_pass = report.get("final_result") == "PASS"
        reconciled = (
            upload.status == "COMPLETED"
            and upload.reconciliation_status == "PASSED"
        )
        source_count = int(source.get("records", upload.source_record_count or 0) or 0)
        stored_count = int(source.get("stored", upload.stored_source_record_count or 0) or 0)
        source_complete = (
            source_count > 0
            and source_count == stored_count
            and int(upload.invalid_metric_count or 0) == 0
        )
        blockers_clear = not any(int(value or 0) for value in critical.values())

        representatives = int(counts.get("representatives", 0) or 0)
        regions = int(counts.get("regions", 0) or 0)
        products = int(counts.get("products", 0) or 0)
        targets = int(counts.get("targets", 0) or 0)
        summaries = int(counts.get("summary", 0) or 0)

        base_ok = final_pass and reconciled and source_complete and blockers_clear
        representatives_ok = base_ok and representatives > 0
        regions_ok = base_ok and regions > 0
        products_ok = base_ok and products > 0

        # A target may legitimately have no IMS exit in the current snapshot,
        # so target and summary row counts are not expected to be identical.
        # The canonical import/reconciliation gate validates the data instead.
        calculations_ok = base_ok and targets > 0 and summaries > 0

        checks = (
            representatives_ok,
            regions_ok,
            products_ok,
            calculations_ok,
            calculations_ok,
        )
        reports[upload.id] = {
            "overall": all(checks),
            "representative_count": representatives,
            "representatives_ok": representatives_ok,
            "region_count": regions,
            "regions_ok": regions_ok,
            "product_count": products,
            "products_ok": products_ok,
            "total_tl_ok": calculations_ok,
            "realization_ok": calculations_ok,
            "sheet_count": int(upload.sheet_count or 0),
            "source_count": source_count,
            "stored_count": stored_count,
        }
    return reports


def install_manager_import_report_alignment():
    """Install the canonical report builder in the existing IMS route module."""
    import app.ims as ims_module

    ims_module._manager_reports = canonical_manager_reports
    ims_module._manager_report = lambda upload: canonical_manager_reports([upload])[upload.id]
