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
