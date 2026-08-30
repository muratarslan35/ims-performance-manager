from pathlib import Path


def test_production_result_audit_is_read_only_and_stage_scoped():
    script = Path("scripts/audit_production_result_sources.py").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/production-result-audit.yml").read_text(encoding="utf-8")

    assert "--stage" in script
    assert "production_stage=args.stage" in script
    assert "ProductionResultImportService(" in script
    assert "_reconcile(upload, report)" in script
    assert "_sha256(source_path)" in script
    assert "upload.source_hash" in script
    assert "db.session.rollback()" in script
    assert "db.session.commit()" not in script
    assert "upload.status =" not in script
    assert "ProductionResultUpload.STATUS_APPLIED" in script
    assert "PRODUCTION_AUDIT_RESULT|PASS" in script
    assert "PRODUCTION_AUDIT_RESULT|FAIL" in script

    assert "workflow_dispatch:" in workflow
    assert "scripts/audit_production_result_sources.py" in workflow
    assert "systemctl restart" not in workflow
    assert "systemctl reload" not in workflow
    assert "git pull" not in workflow
    assert "git status --porcelain" in workflow
