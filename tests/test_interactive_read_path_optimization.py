from pathlib import Path

from app.services.source_read_model_cache import SourceReadModelCache


def test_source_read_model_cache_reuses_build_and_rotates_with_generation():
    SourceReadModelCache.clear()
    calls = []

    def build():
        calls.append(True)
        return {"regions": {"901": "ready"}}

    first = SourceReadModelCache.get_or_build(("market", 2026, 7, 41), build)
    second = SourceReadModelCache.get_or_build(("market", 2026, 7, 41), build)
    third = SourceReadModelCache.get_or_build(("market", 2026, 7, 42), build)

    assert first is second
    assert third == first
    assert len(calls) == 2


def test_interactive_routes_do_not_start_heavy_or_mutating_fallbacks():
    dashboard = Path("app/dashboard.py").read_text(encoding="utf-8")
    regions = Path("app/regions.py").read_text(encoding="utf-8")
    routes = Path("app/routes/__init__.py").read_text(encoding="utf-8")

    assert "service.run()" not in dashboard
    assert "get_or_build" not in dashboard
    assert "enrich_for_period(" not in regions
    assert "upgrade_national_realizations_for_period(" not in regions
    assert "HistoricalRegionReadModelService.get_or_build" not in regions
    assert "HistoricalRegionReadModelService.get_or_build" not in routes
    assert "SourceReadModelCache.get_or_build" in routes


def test_legacy_week32_recovery_is_manual_only():
    workflow = Path(".github/workflows/week32-auto-recovery.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in workflow
    assert "push:" not in workflow
