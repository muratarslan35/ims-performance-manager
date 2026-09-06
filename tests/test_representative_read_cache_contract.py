from __future__ import annotations

import math

from app.cache.representative_analysis_cache import RepresentativeAnalysisCache


def test_source_keyed_representative_cache_has_no_calendar_expiry():
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
    assert math.isinf(expires_at)
    assert math.isinf(RepresentativeAnalysisCache._ttl_for_key(key, 45))


def test_non_representative_cache_key_keeps_requested_ttl_and_short_cap():
    assert RepresentativeAnalysisCache._ttl_for_key("other:key", 45) == 45
    assert RepresentativeAnalysisCache._ttl_for_key("other:key", 9999) == 120


def test_representative_cache_change_does_not_touch_calculation_contracts():
    assert RepresentativeAnalysisCache._SOURCE_KEY_PREFIXES == (
        "rep-market:",
        "rep-intelligence:",
    )
