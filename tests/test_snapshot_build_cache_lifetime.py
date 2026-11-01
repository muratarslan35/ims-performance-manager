from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import pytest

from app.cache.representative_analysis_cache import RepresentativeAnalysisCache as Cache


def test_snapshot_intermediates_are_reused_copied_and_released_between_members():
    Cache.clear()
    calls = []

    def load():
        calls.append(True)
        return {"rows": [len(calls)]}

    for expected in (1, 2):
        with Cache.isolated_build_cache():
            first = Cache.get_or_compute("rep-market:source:scope", load, force_enable=True)
            first["rows"].append(999)
            assert Cache.get_or_compute("rep-market:source:scope", load, force_enable=True) == {"rows": [expected]}
        assert not Cache._store
    assert len(calls) == 2


def test_snapshot_local_cache_is_bounded_and_restores_nested_build():
    with Cache.isolated_build_cache():
        Cache.get_or_compute("parent", lambda: "parent", force_enable=True)
        with Cache.isolated_build_cache():
            assert Cache.get_or_compute("parent", lambda: "nested", force_enable=True) == "nested"
            for index in range(2 * Cache._BUILD_MAX_ENTRIES):
                Cache.get_or_compute(str(index), lambda: [1], force_enable=True)
            assert len(Cache._build_store.get()) == Cache._BUILD_MAX_ENTRIES
        assert Cache.get_or_compute("parent", lambda: "wrong", force_enable=True) == "parent"
    assert Cache._build_store.get() is None


def test_concurrent_snapshot_members_do_not_share_intermediates():
    def member(identity):
        with Cache.isolated_build_cache():
            return Cache.get_or_compute("same-key", lambda: identity, force_enable=True)

    with ThreadPoolExecutor(max_workers=3) as pool:
        assert list(pool.map(member, range(12))) == list(range(12))


def test_sql_projection_is_immutable_and_safe_to_share_on_cache_copy():
    from app.services.representative_query_optimizer import _projection_type

    row = _projection_type(("product_name", "metric_value"))("SOURCE", 0.0)
    assert row.metric_value == 0.0
    assert deepcopy(row) is row
    with pytest.raises(AttributeError):
        row.product_name = "changed"


@pytest.mark.parametrize("value", [None, "", 0, False, "BOS", "BOŞ", "BOSTANCI", "İçel / A-1"])
def test_snapshot_label_memo_preserves_original_normalization(value):
    from app.services.representative_query_optimizer import snapshot_label_key, use_snapshot_upload_ids
    from app.services.alias_service import AliasService

    expected = "".join(ch for ch in AliasService.normalize(value) if ch.isalnum())
    with use_snapshot_upload_ids({}):
        assert snapshot_label_key(value) == expected
        assert snapshot_label_key(value) == expected


def test_generation_authority_false_is_reused_without_database_and_never_leaks():
    from app.services.representative_query_optimizer import use_snapshot_upload_ids, snapshot_authority_status
    from app.services.kpi_market_single_source import _upload_has_authority

    for present in (False, True):
        with use_snapshot_upload_ids({(2026, 10): 7}, authority_by_upload={7: present}):
            # No Flask/DB context exists: this must use the exact generation
            # input, including a valid False, rather than requerying the source.
            assert _upload_has_authority(7) is present
        assert snapshot_authority_status(7) is None


def test_scoped_snapshot_reads_reject_a_changed_generation(monkeypatch):
    from types import SimpleNamespace
    from app.services.persistent_representative_snapshot_service import PersistentRepresentativeSnapshotService as Snap

    monkeypatch.setattr(Snap, "_visible_set_id", classmethod(lambda cls, y, m: 2))
    monkeypatch.setattr(Snap, "source_identity", classmethod(lambda cls, y, m: (7, 0)))
    monkeypatch.setattr(Snap, "_latest_exact_active", classmethod(lambda *args: SimpleNamespace(id=2)))
    with pytest.raises(RuntimeError, match="generation changed"):
        Snap.get_active_many([1], 2026, 9, expected_set_id=1)
    with pytest.raises(RuntimeError, match="generation changed"):
        Snap.get_exact_active_many([1], 2026, 10, expected_set_id=1)
