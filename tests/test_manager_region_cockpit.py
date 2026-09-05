from pathlib import Path


def test_market_analysis_replaces_flat_region_realization_with_dynamic_cockpit():
    template = Path("app/templates/market_analysis.html").read_text(encoding="utf-8")

    assert "Bölgesel Realizasyon Durumu" not in template
    assert "Bölgesel Güncel Durum Merkezi" in template
    assert 'data-manager-period-button="monthly"' in template
    assert 'data-manager-period-button="quarterly"' in template
    assert 'data-manager-period-button="half_year"' in template
    assert 'data-manager-period-button="yearly"' in template
    assert "data-manager-region-button" in template
    assert "managerRegionSnapshotHost" in template


def test_region_workspace_reuses_existing_region_performance_and_market_shapes():
    partial = Path("app/templates/partials/market_region_workspace.html").read_text(encoding="utf-8")

    assert "12 Aylık Bölge Realizasyonu" in partial
    assert "Ürün Bazlı {{ period.label }} Realizasyon" in partial
    assert "BÖLGESEL REKABET VE PAZAR MERKEZİ" in partial
    assert "Rakip Ürünlerin İl Bazlı Çıkış Analizi" in partial
    assert "report.periods" in partial
    assert "report.annual_realization" in partial
    assert "market_analysis.rows" in partial
    assert "market_analysis.rival_groups" in partial


def test_region_cockpit_switches_period_locally_and_region_with_one_fetch():
    script = Path("app/static/js/manager-region-cockpit.js").read_text(encoding="utf-8")

    assert "activePeriod" in script
    assert "fetch(button.dataset.url" in script
    assert "data-manager-period-panel" in script
    assert "initAnnualChart" in script
    assert "Chart.getChart" in script


def test_region_snapshot_cache_is_upload_versioned_and_long_lived():
    route_source = Path("app/routes/__init__.py").read_text(encoding="utf-8")
    cache_source = Path("app/cache/region_manager_snapshot_cache.py").read_text(encoding="utf-8")

    assert "latest_ims_id" in route_source
    assert "production_id" in route_source
    assert 'manager-region:{region_key}:{year}:{month}:{latest_ims_id or 0}:{production_id}:v1' in route_source
    assert "8 * 24 * 60 * 60" in cache_source
    assert "_inflight" in cache_source
