"""Align manager-facing IMS completeness checks with the canonical import gate.

Persisted import audits are the production source of truth for whether an IMS
upload was publishable. Legacy/test uploads that predate that audit evidence
retain the established manager-report fallback.
"""
from __future__ import annotations

from app.models import ImportAuditLog
from app.services.import_result_report import decode_report


_legacy_manager_reports = None


def _report_matches_upload(upload, report):
    """Reject stale audit rows that only happen to share a reused upload id."""
    if int(report.get("upload_id") or 0) != int(upload.id or 0):
        return False
    period = report.get("period") or {}
    if int(period.get("year") or 0) != int(upload.year or 0):
        return False
    if int(period.get("month") or 0) != int(upload.month or 0):
        return False
    report_file = str(report.get("file_name") or "").strip()
    upload_file = str(upload.file_name or "").strip()
    return not report_file or report_file == upload_file


def _latest_reports_for_uploads(uploads):
    uploads_by_id = {
        item.id: item for item in uploads if getattr(item, "id", None) is not None
    }
    ids = list(uploads_by_id)
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
        upload = uploads_by_id.get(audit.upload_id)
        if parsed and upload is not None and _report_matches_upload(upload, parsed):
            reports[audit.upload_id] = parsed
    return reports


def _canonical_report(upload, report):
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

    # A target may legitimately have no IMS exit in the current snapshot, so
    # target and summary row counts are not expected to be identical. The
    # canonical import/reconciliation gate validates the published data.
    calculations_ok = base_ok and targets > 0 and summaries > 0

    checks = (
        representatives_ok,
        regions_ok,
        products_ok,
        calculations_ok,
        calculations_ok,
    )
    return {
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


def canonical_manager_reports(uploads):
    """Use canonical audit evidence when present; preserve old-data fallback."""
    if not uploads:
        return {}

    canonical = _latest_reports_for_uploads(uploads)
    reports = {}
    legacy_uploads = []
    for upload in uploads:
        report = canonical.get(upload.id)
        if report:
            reports[upload.id] = _canonical_report(upload, report)
        else:
            legacy_uploads.append(upload)

    if legacy_uploads and _legacy_manager_reports is not None:
        reports.update(_legacy_manager_reports(legacy_uploads))
    return reports


def install_manager_import_report_alignment():
    """Install canonical reporting without breaking pre-audit/test uploads."""
    global _legacy_manager_reports
    import app.ims as ims_module

    if _legacy_manager_reports is None:
        _legacy_manager_reports = ims_module._manager_reports
    ims_module._manager_reports = canonical_manager_reports
    ims_module._manager_report = lambda upload: canonical_manager_reports([upload])[upload.id]
