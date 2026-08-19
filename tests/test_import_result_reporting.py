from app.services.import_result_report import (
    REPORT_MARKER,
    _manager_message,
    decode_report,
    encode_report,
)


def _report(final_result="PASS"):
    return {
        "marker": REPORT_MARKER,
        "final_result": final_result,
        "upload_id": 42,
        "generated_at": "2026-08-20T00:00:00",
        "sheets": {"verified": 16, "total": 16},
        "source": {"records": 28091, "stored": 28091, "zero_metrics": 7},
        "counts": {
            "facts": 3164,
            "summary": 791,
            "targets": 791,
            "competition": 99756,
            "official_brick_spread": 904,
            "representatives": 113,
            "vacancies": 2,
            "products": 7,
            "regions": 11,
        },
        "matches": {"auto_repaired": 3},
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
        "previous_ims_delta": {
            "sales_changed": 4,
            "targets_changed": 1,
            "region_cadre_changed": 2,
            "brick_spread_changed": 3,
            "competition_changed": 5,
        },
    }


def test_manager_report_roundtrip_keeps_structured_audit_payload():
    report = _report()
    assert decode_report(encode_report(report)) == report
    assert decode_report("legacy warning text") is None


def test_pass_message_contains_all_manager_gate_counts():
    message = _manager_message(_report())
    assert "IMS eksiksiz ve hatasız içe aktarıldı" in message
    assert "Sayfa 16/16" in message
    assert "kaynak/kayıt 28091/28091" in message
    assert "fact 3164" in message
    assert "summary 791" in message
    assert "hedef 791" in message
    assert "rekabet 99756" in message
    assert "resmi brick 904" in message
    assert "bölge 11" in message
    assert "bölge/kadro 2" in message


def test_fail_message_never_claims_complete_import():
    report = _report("FAIL")
    report["critical"]["unclassified_sheet"] = 1
    message = _manager_message(report)
    assert "yayınlanmadı" in message
    assert "eksiksiz ve hatasız" not in message
