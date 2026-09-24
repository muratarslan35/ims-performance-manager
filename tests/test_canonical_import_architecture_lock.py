from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_canonical_import_architecture_document_is_present_and_locked():
    doc = (ROOT / "IMS_IMPORT_READ_ARCHITECTURE_LOCK.md").read_text(encoding="utf-8")
    canonical = (ROOT / "CANONICAL_LOCKS.md").read_text(encoding="utf-8")

    assert "KİLİTLİ / PRODUCTION KANONİK" in doc
    assert "Dosya yüklenir → otomatik doğrulanır" in doc
    assert "P2 üretim > P1 üretim > IMS" in doc
    assert "Dashboard + region + representative" in doc
    assert "snapshot/read-model" in doc
    assert "muratarslan35" in doc
    assert "IMS_IMPORT_READ_ARCHITECTURE_LOCK.md" in canonical
    assert "Import otomasyonu kilidi" in canonical
    assert "Snapshot-only interaktif okuma kilidi" in canonical
    assert "Atomik publication kilidi" in canonical
    assert "Ranking kilidi" in canonical
    assert "Market payload bütünlüğü kilidi" in canonical


def test_locked_contract_workflow_covers_import_and_read_model_core():
    workflow = (ROOT / ".github/workflows/locked-contracts.yml").read_text(
        encoding="utf-8"
    )

    required_paths = [
        "app/ims.py",
        "ims_import_worker.py",
        "app/services/ims_import_service.py",
        "app/services/ims_import_queue.py",
        "app/services/ims_publication_service.py",
        "app/services/workbook_preflight.py",
        "app/services/semantic_import_discovery.py",
        "app/services/dynamic_import_contract.py",
        "app/services/kpi_workbook_compat.py",
        "app/services/kpi_market_single_source.py",
        "app/services/competition_import_service.py",
        "app/services/official_aggregate_service.py",
        "app/services/persistent_dashboard_snapshot_service.py",
        "app/services/persistent_region_snapshot_service.py",
        "app/services/persistent_representative_snapshot_service.py",
        "app/services/representative_snapshot_refresh_queue.py",
        "app/services/historical_region_read_model_service.py",
        "app/services/region_box_authority_guard.py",
        "app/services/production_result_service.py",
        "app/services/region_performance_service.py",
        "app/services/region_market_service.py",
        "app/query/dashboard_query.py",
        "app/routes/__init__.py",
        "app/regions.py",
        "IMS_IMPORT_READ_ARCHITECTURE_LOCK.md",
    ]
    for path in required_paths:
        assert path in workflow, path


def test_locked_contract_requires_verified_repository_owner_approval_after_bootstrap():
    workflow = (ROOT / ".github/workflows/locked-contracts.yml").read_text(
        encoding="utf-8"
    )

    assert "OWNER-APPROVAL-GUARD-V1" in workflow
    assert "LOCK_OWNER: muratarslan35" in workflow
    assert "pull-requests: read" in workflow
    assert "issues: read" in workflow
    assert "/pulls/$PR_NUMBER/reviews?per_page=100" in workflow
    assert "/issues/$PR_NUMBER/comments?per_page=100" in workflow
    assert "LOCKED-CONTRACT-APPROVED: YES" in workflow
    assert "LOCKED_OWNER_APPROVAL|present" in workflow
    assert "bootstrap-current-user-approval" in workflow


def test_import_core_changes_still_run_import_release_gates():
    deploy = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")

    assert "ims_import_worker.py" in deploy
    assert "app/services/ims_import_service.py" in deploy
    assert "app/services/*import*" in deploy
    assert "app/services/competition*" in deploy
    assert "app/services/kpi_workbook_compat.py" in deploy
    assert 'mode="import"' in deploy
    assert "Import full suite" in deploy
    assert "PR 50-upload scale probe" in deploy
    assert "verify_live_ims_gate.py" in deploy
