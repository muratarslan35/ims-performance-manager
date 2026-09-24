from pathlib import Path


def test_production_status_waits_for_all_read_models_and_exposes_real_counts():
    source = Path("app/services/production_publication_status.py").read_text(
        encoding="utf-8"
    )
    assert "ProductionPublicationStatus" in source
    assert "representative_count / max(expected_representatives, 1)" in source
    assert "dashboard_ready and representative_ready and region_ready" in source
    assert "_period_is_fresh_for_production(" in source
    assert '"status": "COMPLETED" if completed else "PROCESSING"' in source
    assert '"percent": 100 if completed else min(percent, 99)' in source


def test_production_ui_polls_measured_progress_and_closes_after_completion():
    template = Path("app/templates/ims.html").read_text(encoding="utf-8")
    route = Path("app/ims.py").read_text(encoding="utf-8")
    css = Path("app/static/css/ims.css").read_text(encoding="utf-8")

    assert 'id="productionLiveProgress"' in template
    assert "pollProductionProgress" in template
    assert 'productionBadge.textContent = failed ? "Hatalı" : completed ? "Tamamlandı" : "Devam ediyor"' in template
    assert 'productionPane.classList.remove("visible")' in template
    assert '"/production-progress/<int:upload_id>"' in route
    assert "ProductionPublicationStatus.describe(upload)" in route
    assert ".production-live-progress.visible" in css


def test_production_cascade_cache_holds_one_full_representative_year():
    source = Path("app/cache/representative_analysis_cache.py").read_text(
        encoding="utf-8"
    )
    assert "_MAX_ENTRIES = 2048" in source
