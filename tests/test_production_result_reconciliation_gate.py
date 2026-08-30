from pathlib import Path


def test_production_result_reconciliation_gate_contract():
    source = Path("app/services/production_result_reconciliation_gate.py").read_text(encoding="utf-8")
    app_source = Path("app/__init__.py").read_text(encoding="utf-8")
    retry_source = Path("app/services/production_result_retry_ui.py").read_text(encoding="utf-8")

    # APPLIED is revoked until all DB layers have been flushed and compared back
    # to the parsed source report.
    assert "upload.status = upload.STATUS_VALIDATED" in source
    assert "db.session.flush()" in source
    assert "_reconcile(upload, report)" in source
    assert "upload.status = upload.STATUS_APPLIED" in source
    assert source.index("upload.status = upload.STATUS_VALIDATED") < source.index("_reconcile(upload, report)")
    assert source.index("_reconcile(upload, report)") < source.index("upload.status = upload.STATUS_APPLIED")

    for model_name in (
        "ProductionResult",
        "ProductionRepresentativeTotal",
        "ProductionRegionProductResult",
        "ProductionRegionTotal",
        "ProductionNationalProductResult",
        "ProductionNationalTotal",
    ):
        assert model_name in source

    for field in (
        "target_tl",
        "target_unit",
        "actual_tl",
        "actual_unit",
        "realization_percent",
        "unit_realization_percent",
    ):
        assert field in source

    assert "Kaynak Excel ↔ DB final eşleşmesi %100 doğrulandı." in source
    assert "install_production_result_reconciliation_gate()" in app_source

    # Retry UI must visibly switch to a yellow reviewing state while the request
    # is still running; green is only rendered after the server returns APPLIED.
    assert "bg-warning text-dark" in retry_source
    assert "İnceleniyor" in retry_source
    assert "Doğrulanıyor..." in retry_source


def test_stage_is_recovered_from_protected_staging_name_when_route_omits_it():
    source = Path("app/services/production_result_reconciliation_gate.py").read_text(encoding="utf-8")
    assert 're.search(r"-u([12])-", str(file_path))' in source
    assert "production_stage = int(match.group(1))" in source
