from pathlib import Path


def test_market_analysis_replaces_flat_region_realization_with_dynamic_cockpit():
    template = Path("app/templates/market_analysis.html").read_text(encoding="utf-8")

    assert "Bölgesel Realizasyon Durumu" not in template
    assert "Bölgesel Güncel Durum Merkezi" in template
    assert 'data-manager-period-button="monthly"' in template
    assert 'data-manager-period-button="q1"' in template
    assert 'data-manager-period-button="q2"' in template
    assert 'data-manager-period-button="q3"' in template
    assert 'data-manager-period-button="q4"' in template
    assert 'data-manager-period-button="half_year"' in template
    assert 'data-manager-period-button="yearly"' in template
    assert 'data-manager-period-button="quarterly"' not in template
    assert "manager-period-row-wide" in template
    assert "manager-period-row-compact" in template
    assert "data-manager-region-button" in template
    assert "managerRegionSnapshotHost" in template


def test_region_workspace_reuses_existing_region_performance_and_market_shapes():
    partial = Path("app/templates/partials/market_region_workspace.html").read_text(encoding="utf-8")

    assert "12 Aylık Bölge Realizasyonu" in partial
    assert "Ürün Bazlı {{ period.label }} Realizasyon" in partial
    assert "{{ report.region_name }} Bölgesi Ürün ve Rakip Analizi" in partial
    assert "Rakip Ürünlerin İl Bazlı Çıkış Analizi" in partial
    assert "report.periods" in partial
    assert "'q1','q2','q3','q4'" in partial
    assert "report.annual_realization" in partial
    assert "market_analysis.rows" in partial
    assert "market_analysis.rival_groups" in partial


def test_quota_badge_is_visible_only_in_monthly_panel_without_changing_values():
    partial = Path("app/templates/partials/market_region_workspace.html").read_text(encoding="utf-8")

    assert "key == 'monthly' and item.quota_exit" in partial
    assert "item.target_tl" in partial
    assert "item.actual_tl" in partial
    assert "item.unit_difference" in partial
    assert "item.gap_tl" in partial


def test_product_realization_and_deltas_use_region_status_colors():
    partial = Path("app/templates/partials/market_region_workspace.html").read_text(encoding="utf-8")
    css = Path("app/static/css/manager-region-cockpit.css").read_text(encoding="utf-8")

    assert "item.realization_percent >= 90" in partial
    assert "item.realization_percent >= 70" in partial
    assert "item.unit_difference > 0" in partial
    assert "item.gap_tl < 0" in partial
    assert ".manager-realization-pill.good" in css
    assert ".manager-realization-pill.watch" in css
    assert ".manager-realization-pill.risk" in css
    assert ".manager-delta.positive" in css
    assert ".manager-delta.negative" in css


def test_region_cockpit_switches_period_locally_and_reuses_browser_snapshot_cache():
    script = Path("app/static/js/manager-region-cockpit.js").read_text(encoding="utf-8")

    assert "activePeriod" in script
    assert "regionHtmlCache" in script
    assert "regionInflight" in script
    assert "fetchRegionHtml" in script
    assert "prefetchRegion" in script
    assert "loadSequence" in script
    assert "data-manager-period-panel" in script
    assert "initAnnualChart" in script
    assert "Chart.getChart" in script


def test_region_cockpit_uses_durable_snapshot_or_source_versioned_historical_read_model():
    route_source = Path("app/routes/__init__.py").read_text(encoding="utf-8")
    historical_source = Path(
        "app/services/historical_region_read_model_service.py"
    ).read_text(encoding="utf-8")

    assert "PersistentRegionSnapshotService.get_active" in route_source
    assert "HistoricalRegionReadModelService.get_active" in route_source
    assert "HistoricalRegionReadModelService.get_or_build" not in route_source
    assert "RegionPerformanceService(" not in route_source
    assert "RegionMarketService(" not in route_source
    assert "PersistentRegionSnapshotService.source_identity" in historical_source
    assert "production_upload_id" in historical_source
    assert "fcntl.flock" in historical_source
