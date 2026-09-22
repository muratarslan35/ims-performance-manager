from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "app/services/snapshot_generation_identity_guard.py"
HOOKS = ROOT / "app/services/ims_upload_lifecycle_hooks.py"


def test_guard_is_installed_from_existing_ims_lifecycle_hook():
    hooks = HOOKS.read_text(encoding="utf-8")
    assert "install_snapshot_generation_identity_guard" in hooks
    assert "install_snapshot_generation_identity_guard()" in hooks


def test_dashboard_generation_requires_snapshot_not_to_predate_current_upload():
    source = GUARD.read_text(encoding="utf-8")
    assert "source_completed = _source_completed_at(upload_id)" in source
    assert "return generation_created >= source_completed" in source
    assert "def generation_ready" in source
    assert "def get_active" in source
    assert "created_at=envelope.get(\"created_at\")" in source


def test_region_generation_collision_is_rebuilt_in_place():
    source = GUARD.read_text(encoding="utf-8")
    assert "region_snapshots.delete().where(region_snapshots.c.set_id == stale_set_id)" in source
    assert "status=guarded_cls.STATUS_BUILDING" in source
    assert "region_count=0" in source
    assert "created_at=datetime.utcnow()" in source


def test_representative_stale_exact_generation_cannot_be_reused():
    source = GUARD.read_text(encoding="utf-8")
    assert "def invalidate_stale_exact" in source
    assert "cls.STATUS_SUPERSEDED" in source
    assert "cls.STATUS_FAILED" in source
    assert "representative_snapshot_sets.c.source_upload_id != int(ims_id)" in source


def test_permanent_delete_purges_derived_generations_for_deleted_upload_id():
    source = GUARD.read_text(encoding="utf-8")
    assert "region_snapshot_sets.c.source_upload_id == int(upload_id)" in source
    assert "representative_snapshot_sets.c.source_upload_id == int(upload_id)" in source
    assert "dashboard-{year:04d}-{month:02d}-ims{int(upload_id)}-production*.json" in source
    assert "legacy.unlink(missing_ok=True)" in source

def test_dashboard_identity_guard_preserves_atomic_publication_gate():
    source = GUARD.read_text(encoding="utf-8")
    start = source.index("def _install_dashboard_guard")
    end = source.index("def _install_region_guard", start)
    block = source[start:end]
    assert "original_get_active = cls.get_active" in block
    assert "IMSPublicationService.pending_job(year, month) is not None" in block
    assert "return original_get_active(year, month)" in block

