from pathlib import Path


def test_production_result_reconciliation_gate_contract():
    source = Path("app/services/production_result_reconciliation_gate.py").read_text(encoding="utf-8")
    app_source = Path("app/__init__.py").read_text(encoding="utf-8")
    retry_source = Path("app/services/production_result_retry_ui.py").read_text(encoding="utf-8")

    # Source integrity is automatic and must execute before the original apply,
    # so first upload, retry and any future caller share the same fail-closed gate.
    gated_apply = source[source.index("def _gated_apply") : source.index("def _stage_aware_init")]
    assert "_assert_source_integrity(upload)" in gated_apply
    assert "_ORIGINAL_APPLY(upload, report)" in gated_apply
    assert gated_apply.index("_assert_source_integrity(upload)") < gated_apply.index("_ORIGINAL_APPLY(upload, report)")

    source_integrity = source[source.index("def _assert_source_integrity") : source.index("def _equal_number")]
    assert 'current_app.config["UPLOAD_FOLDER"]' in source_integrity
    assert '"production_results"' in source_integrity
    assert "source_path.is_file()" in source_integrity
    assert "actual_hash = _sha256(source_path)" in source_integrity
    assert "actual_hash != expected_hash" in source_integrity
    assert "SHA-256" in source_integrity

    # APPLIED is revoked until all DB layers have been flushed and compared back
    # to the parsed source report. Scope ordering checks to _gated_apply itself so
    # the earlier _reconcile function definition cannot be mistaken for the call.
    assert "upload.status = upload.STATUS_VALIDATED" in gated_apply
    assert "db.session.flush()" in gated_apply
    assert "_reconcile(upload, report)" in gated_apply
    assert "upload.status = upload.STATUS_APPLIED" in gated_apply
    assert gated_apply.index("upload.status = upload.STATUS_VALIDATED") < gated_apply.index("_reconcile(upload, report)")
    assert gated_apply.index("_reconcile(upload, report)") < gated_apply.index("upload.status = upload.STATUS_APPLIED")

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

    assert "Kaynak dosya SHA-256 bütünlüğü ve Excel ↔ DB final eşleşmesi %100 otomatik doğrulandı." in source
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


def test_second_production_is_not_conditioned_on_first_production_presence():
    source = Path("app/services/production_result_reconciliation_gate.py").read_text(encoding="utf-8")
    # Stage resolution is local to the uploaded/staged workbook. The gate must not
    # query for or require a stage-1 upload before allowing stage 2 to validate.
    assert "production_stage = int(match.group(1))" in source
    assert "production_stage == 1" not in source
    assert "production_stage != 1" not in source
    assert "STATUS_APPLIED" in source
