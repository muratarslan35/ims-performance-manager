from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_july_quota_refresh_verifies_hidden_dashboard_generation_before_publication():
    source = (ROOT / "scripts/refresh_july_quota_read_models.py").read_text(encoding="utf-8")

    staged = source[source.index("if blocked_job is None:"):source.index("REPRESENTATIVE_READ_MODEL|STAGED")]
    assert "PersistentDashboardSnapshotService.get_generation_for_source(" in staged
    assert "args.year, month, ims_id, production_id" in staged
    assert "PersistentDashboardSnapshotService.get_active(args.year, month)" not in staged

    published = source[source.index("IMS_PUBLICATION_RECOVERED"):]
    assert "PersistentDashboardSnapshotService.get_active(args.year, month)" in published
    compile(source, "scripts/refresh_july_quota_read_models.py", "exec")


def test_july_quota_refresh_repairs_only_stale_representative_members():
    refresh = (ROOT / "scripts/refresh_july_quota_read_models.py").read_text(encoding="utf-8")
    snapshot = (ROOT / "app/services/persistent_representative_snapshot_service.py").read_text(encoding="utf-8")

    assert "stale_representatives = []" in refresh
    assert "PersistentRepresentativeSnapshotService.rebuild_exact_members(" in refresh
    assert "REPRESENTATIVE_QUOTA_REPAIR|PASS" in refresh
    assert "def rebuild_exact_members" in snapshot
    assert "representative_snapshots.delete()" in snapshot
    assert "status=cls.STATUS_BUILDING" in snapshot
    assert "with cls._snapshot_writer_lock():" in snapshot
    assert "result = cls._build_for_period_unlocked(year, month, force=False)" in snapshot


def test_july_quota_maintenance_does_not_rebuild_later_months():
    source = (ROOT / "scripts/refresh_july_quota_read_models.py").read_text(encoding="utf-8")

    assert "for month in (args.month,):" in source
    assert "range(args.month, end_month + 1)" not in source
    assert "RepresentativeSnapshotRefreshQueue" in source


def test_july_acceptance_reads_representative_snapshots_and_targets_in_bulk():
    source = (ROOT / "scripts/refresh_july_quota_read_models.py").read_text(encoding="utf-8")
    acceptance = source[source.index('raise RuntimeError("Published July region snapshots unavailable")'):]

    assert "PersistentRepresentativeSnapshotService._payloads_from_set(exact.id, ids)" in acceptance
    assert "Target.representative_id.in_(ids)" in acceptance
    assert "PersistentRepresentativeSnapshotService.get_active(" not in acceptance


def test_fast_july_acceptance_requires_region_ai_enrichment():
    source = (ROOT / "scripts/verify_july_quota_read_models.py").read_text(encoding="utf-8")

    assert 'isinstance((payload or {}).get("ai_report"), dict)' in source
    assert "AI enrichment unavailable" in source


def test_july_dashboard_repair_is_national_only():
    source = (ROOT / "scripts/repair_july_quota_dashboard.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/july-fentivag-quota-refresh.yml").read_text(encoding="utf-8")

    assert "DashboardService(year=year, month=month).run()" in source
    assert "PersistentDashboardSnapshotService.publish(year, month, payload)" in source
    assert "PersistentRegionSnapshotService" not in source
    assert "PersistentRepresentativeSnapshotService" not in source
    assert "repair_july_quota_dashboard" in workflow
    assert workflow.index("repair_july_quota_dashboard") < workflow.index("verify_july_quota_read_models")
    compile(source, "scripts/repair_july_quota_dashboard.py", "exec")


def test_july_representative_repair_is_selective_only():
    source = (ROOT / "scripts/repair_july_quota_representatives.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/july-fentivag-quota-refresh.yml").read_text(encoding="utf-8")

    assert "PersistentRepresentativeSnapshotService.rebuild_exact_members(" in source
    assert "PersistentRepresentativeSnapshotService.build_for_period(" not in source
    assert "JULY_REPRESENTATIVE_QUOTA_REPAIR|PASS" in source
    assert "repair_july_quota_representatives" in workflow
    assert workflow.index("repair_july_quota_dashboard") < workflow.index("repair_july_quota_representatives") < workflow.index("verify_july_quota_read_models")
    compile(source, "scripts/repair_july_quota_representatives.py", "exec")
