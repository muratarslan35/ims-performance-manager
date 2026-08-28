from pathlib import Path


def test_assignment_upsert_uses_import_local_unique_key_cache():
    source = Path("app/services/ims_import_service.py").read_text(encoding="utf-8")
    assert "self._brick_assignment_cache = {}" in source
    start = source.index("def _upsert_auto_brick_assignment")
    end = source.index("def sync_brick_assignments", start)
    block = source[start:end]
    assert "key = (int(representative_id), int(year), int(month), str(brick))" in block
    assert "self._brick_assignment_cache.get(key)" in block
    assert "self._brick_assignment_cache[key] = assignment" in block
    assert "assignment.source != \"MANUAL\"" in block
