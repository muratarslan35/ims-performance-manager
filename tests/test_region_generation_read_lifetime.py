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


def test_snapshot_monthly_market_uses_member_cache_and_keeps_period_mutations_isolated(monkeypatch):
    from copy import deepcopy
    from app.services import representative_period_workspace as workspace
    from app.services.representative_query_optimizer import use_snapshot_upload_ids
    from app.cache.representative_analysis_cache import RepresentativeAnalysisCache as Cache

    product = SimpleNamespace(id=1, product_name="PRODUCT", display_order=1)
    months = [(2026, 1), (2026, 2)]
    calls = []

    def monthly(cls, representative, year, month, source, loader):
        calls.append(month)
        actual = 0.0 if month == 1 else 5.0
        return {"rows": [{"product": product, "actual_unit": actual,
                         "target_unit": 10.0, "market_unit": actual + 3,
                         "competitor_unit": 3.0, "rivals": [{"name": "RIVAL", "unit": 3.0}]}]}

    monkeypatch.setattr(workspace, "_market_source_cache_key", lambda rep, year, month: f"rep-market:test:{year}:{month}")
    monkeypatch.setattr(workspace.RepresentativeMonthlyMarketCache, "get_or_compute", classmethod(monthly))
    Cache.clear()
    expected = workspace._aggregate_market(SimpleNamespace(id=1), months)
    calls.clear()

    def redundant_cache(*args, **kwargs):
        raise AssertionError("snapshot composition must not copy a second cache")

    monkeypatch.setattr(Cache, "get_or_compute", redundant_cache)
    with use_snapshot_upload_ids({}):
        member_cache = {}
        single = workspace._aggregate_market(SimpleNamespace(id=1), months[:1], market_cache=member_cache)
        single["rows"][0]["actual_unit"] = 999
        single["rows"][0]["rivals"].append({"name": "MUTATED", "unit": 999})
        actual = workspace._aggregate_market(SimpleNamespace(id=1), months, market_cache=member_cache)
        assert actual == expected
        assert member_cache[months[0]]["rows"][0]["actual_unit"] == 0.0
        assert member_cache[months[0]]["rows"][0]["rivals"] == [{"name": "RIVAL", "unit": 3.0}]
        assert calls == [1, 2]
    Cache.clear()
