from concurrent.futures import ThreadPoolExecutor
import time
from unittest.mock import patch

from app.cache.dashboard_cache import DashboardCache


def _empty_cache():
    DashboardCache().invalidate_prefix("dashboard:v3")


def test_dashboard_cache_returns_isolated_payload_copy():
    _empty_cache()
    cache = DashboardCache()
    payload = {"products": [{"name": "Travazol"}], "cache": {"hit": False}}

    cache.set("dashboard:v3:2026:1:rep_None", payload, ttl_seconds=60)
    first = cache.get("dashboard:v3:2026:1:rep_None")
    first["products"][0]["name"] = "Changed"

    second = cache.get("dashboard:v3:2026:1:rep_None")
    assert second["products"][0]["name"] == "Travazol"


def test_dashboard_cache_expires_and_invalidates_by_prefix():
    _empty_cache()
    cache = DashboardCache()

    with patch("app.cache.dashboard_cache.time.monotonic", return_value=100.0):
        cache.set("dashboard:v3:2026:1:rep_None", {"value": 1}, ttl_seconds=300)
        cache.set("dashboard:v3:2026:2:rep_None", {"value": 2}, ttl_seconds=300)

    with patch("app.cache.dashboard_cache.time.monotonic", return_value=161.0):
        assert cache.get("dashboard:v3:2026:1:rep_None") is None

    cache.invalidate_prefix("dashboard:v3:2026")
    assert cache.get("dashboard:v3:2026:2:rep_None") is None


def test_dashboard_cache_does_not_store_representative_specific_payloads():
    _empty_cache()
    cache = DashboardCache()
    cache.set("dashboard:v3:2026:1:rep_42", {"value": "private"}, ttl_seconds=60)
    assert cache.get("dashboard:v3:2026:1:rep_42") is None


def test_dashboard_cache_coalesces_concurrent_cold_reads():
    _empty_cache()
    cache = DashboardCache()
    key = "dashboard:v3:2026:1:rep_None"

    assert cache.get(key) is None
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(cache.get, key) for _ in range(6)]
        time.sleep(0.05)
        cache.set(key, {"value": "ready"}, ttl_seconds=60)
        results = [future.result(timeout=2) for future in futures]

    assert results == [{"value": "ready"}] * 6
