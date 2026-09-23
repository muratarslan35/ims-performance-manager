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
