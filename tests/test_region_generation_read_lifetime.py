from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app.cache.ims_generation_reads import generation_reads, isolated_generation_reads


def test_authority_lookup_reuses_ids_and_missing_result_only_inside_one_generation(monkeypatch):
    from app.services import kpi_market_single_source as source

    answers = iter([SimpleNamespace(id=11), None, SimpleNamespace(id=12), None])
    calls = []

    class Query:
        def __getattr__(self, name):
            return lambda *args, **kwargs: self

        def first(self):
            calls.append(True)
            return next(answers)

    fresh_session_row = SimpleNamespace(id=11)
    session = SimpleNamespace(query=lambda *args: Query(), get=lambda model, uid: fresh_session_row)
    monkeypatch.setattr(source, "db", SimpleNamespace(session=session))
    with isolated_generation_reads():
        assert source._latest_authority_upload(2026, 10).id == 11
        assert source._latest_authority_upload(2026, 10) is fresh_session_row
        assert source._latest_authority_upload(2026, 9) is None
        assert source._latest_authority_upload(2026, 9) is None
        assert len(calls) == 2
        assert all(isinstance(value, int) or value is None for value in generation_reads().values())
    # Interactive/non-generation readers always rediscover current authority.
    assert source._latest_authority_upload(2026, 10).id == 12
    assert source._latest_authority_upload(2026, 10) is None
    assert len(calls) == 4


def test_generation_scope_is_restored_on_failure_and_isolated_between_threads():
    with isolated_generation_reads():
        generation_reads()["source"] = 1
        with pytest.raises(RuntimeError):
            with isolated_generation_reads():
                assert generation_reads() == {}
                generation_reads()["source"] = 2
                raise RuntimeError("failed generation")
        assert generation_reads() == {"source": 1}
    assert generation_reads() is None

    def member(value):
        with isolated_generation_reads():
            generation_reads()["source"] = value
            return generation_reads()["source"]

    with ThreadPoolExecutor(max_workers=3) as pool:
        assert list(pool.map(member, range(12))) == list(range(12))
    assert generation_reads() is None


def test_region_product_memo_keeps_matching_order_missing_values_and_catalog_changes(monkeypatch):
    from app.services.region_market_service import RegionMarketService

    first = SimpleNamespace(id=1, product_name="TRAVAZOL", product_code="TRAVAZOL", ims_name=None, competitor_group="ORTAK")
    second = SimpleNamespace(id=2, product_name="MONUROL", product_code="MONUROL", ims_name=None, competitor_group="ORTAK")
    products = [first, second]
    service = RegionMarketService("101", [], 2026, 10)
    original = service._match_product_for
    calls = []

    def match(*args):
        calls.append(True)
        return original(*args)

    monkeypatch.setattr(service, "_match_product_for", match)
    assert service._product_for("ORTAK", None, products) is first
    assert service._product_for("ORTAK", None, products) is first
    assert service._product_for("BILINMEYEN", "BOS", products) is None
    assert service._product_for("BILINMEYEN", "BOS", products) is None
    assert len(calls) == 2
    first.competitor_group = "YENI"
    assert service._product_for("ORTAK", None, products) is second
    assert len(calls) == 3
    assert RegionMarketService("101", [], 2026, 10)._product_matches == {}
