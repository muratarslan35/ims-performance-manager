from types import SimpleNamespace

from app.services import manager_import_report_alignment as alignment


def _upload(**overrides):
    values = dict(
        id=13,
        status="COMPLETED",
        reconciliation_status="PASSED",
        source_record_count=21105,
        stored_source_record_count=21105,
        invalid_metric_count=0,
        sheet_count=16,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _report(**overrides):
    report = {
        "final_result": "PASS",
        "source": {"records": 21105, "stored": 21105},
        "critical": {
            "unclassified_sheet": 0,
            "unclassified_master_cell": 0,
            "unresolved_representative": 0,
            "unresolved_product": 0,
            "invalid_metric": 0,
            "row_error": 0,
            "conflicting_match": 0,
            "duplicate_conflict": 0,
        },
        "counts": {
            "representatives": 113,
            "regions": 11,
            "products": 7,
            "targets": 1211,
            "summary": 791,
        },
    }
    report.update(overrides)
    return report


def test_passed_week8_report_does_not_require_target_summary_cardinality(monkeypatch):
    monkeypatch.setattr(alignment, "_latest_reports_for_uploads", lambda uploads: {13: _report()})
    result = alignment.canonical_manager_reports([_upload()])[13]

    assert result["overall"] is True
    assert result["representative_count"] == 113
    assert result["region_count"] == 11
    assert result["product_count"] == 7
    assert result["total_tl_ok"] is True
    assert result["realization_ok"] is True


def test_blocker_keeps_manager_report_failed(monkeypatch):
    report = _report()
    report["critical"]["invalid_metric"] = 1
    monkeypatch.setattr(alignment, "_latest_reports_for_uploads", lambda uploads: {13: report})

    result = alignment.canonical_manager_reports([_upload()])[13]
    assert result["overall"] is False
    assert result["total_tl_ok"] is False
    assert result["realization_ok"] is False


def test_duplicate_import_result_flash_is_not_registered():
    source = open("app/__init__.py", encoding="utf-8").read()
    assert "register_import_result_flash(app)" not in source
