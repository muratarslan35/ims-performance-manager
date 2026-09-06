from __future__ import annotations

import time

from app.cache.representative_analysis_cache import RepresentativeAnalysisCache


def test_source_keyed_representative_cache_outlives_short_callsite_ttl():
    RepresentativeAnalysisCache.clear()
    calls = []

    def loader():
        calls.append(1)
        return {"value": 7}

    key = "rep-market:42:2026:4:32:scope"
    first = RepresentativeAnalysisCache.get_or_compute(
        key, loader, ttl_seconds=45, force_enable=True
    )
    second = RepresentativeAnalysisCache.get_or_compute(
        key, loader, ttl_seconds=45, force_enable=True
    )

    assert first == second == {"value": 7}
    assert len(calls) == 1
    expires_at, _payload = RepresentativeAnalysisCache._store[key]
    assert expires_at - time.monotonic() > 7 * 24 * 60 * 60


def test_non_representative_cache_key_keeps_requested_ttl():
    assert RepresentativeAnalysisCache._ttl_for_key("other:key", 45) == 45


def test_representative_cache_change_does_not_touch_calculation_contracts():
    assert RepresentativeAnalysisCache._SOURCE_KEY_PREFIXES == (
        "rep-market:",
        "rep-intelligence:",
    )
