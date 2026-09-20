from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_executive_cockpit_is_a_single_glance_summary_before_region_drilldown():
    template = (ROOT / "app/templates/market_analysis.html").read_text(encoding="utf-8")
    partial = (ROOT / "app/templates/partials/executive_market_cockpit.html").read_text(encoding="utf-8")
    javascript = (ROOT / "app/static/js/executive-market-cockpit.js").read_text(encoding="utf-8")

    assert template.index('{% include "partials/executive_market_cockpit.html" %}') < template.index('<section class="manager-region-cockpit"')
    assert "data-exec-period-button" in partial
    assert "Türkiye Güncel Durum ve Rekabet Özeti" in partial
    assert "Bölge Performans Tablosu" in partial
    assert "Türkiye İlk 5 Rakip" in partial
    assert "Türkiye Ürün Portföy Matrisi" not in partial
    assert "Fırsat ve Risk Bölgeleri" not in partial
    assert "Türkiye Realizasyon Trendi" not in partial
    assert "Türkiye AI Ticari Aksiyon Merkezi" not in partial
    assert "Bölgesel AI Yönetim İçgörüleri" not in partial
    assert "TR kutu payı farkı" in partial
    assert "Kutu payı" in partial
    assert "Realizasyon" in partial
    assert "Şirket kutu" in partial
    assert "Rakip kutu" in partial
    assert "data-exec-ai-panel" not in partial
    assert "region.share_gap_to_national" not in partial
    assert "region.unit_share_gap_to_national" in partial
    assert "openRegion" in javascript
    assert "Chart.getChart" not in javascript
    assert "data-exec-region-key" in partial
    assert 'event.key' in javascript


def test_executive_client_only_switches_period_and_opens_region_detail():
    javascript = (ROOT / "app/static/js/executive-market-cockpit.js").read_text(encoding="utf-8")
    assert "setPeriod" in javascript
    assert "openRegion" in javascript
    assert "scrollIntoView" in javascript
    assert "new Chart" not in javascript
    assert "MutationObserver" not in javascript


def test_executive_region_table_keeps_theme_contrast():
    clarity = (ROOT / "app/static/css/market-analysis-exec-clarity.css").read_text(
        encoding="utf-8"
    )

    assert ".exec-region-table" in clarity
    assert ".exec-status-pill.good" in clarity
    assert ".exec-status-pill.watch" in clarity
    assert ".exec-status-pill.risk" in clarity
    assert '[data-theme="dark"] .exec-region-table th' in clarity
    assert '[data-theme="dark"] .exec-region-table td' in clarity


def test_executive_read_model_reuses_durable_snapshot_payloads_without_db_queries():
    service = (ROOT / "app/services/executive_market_cockpit_service.py").read_text(encoding="utf-8")
    routes = (ROOT / "app/routes/__init__.py").read_text(encoding="utf-8")

    assert "performs no database queries" in service
    assert "ExecutiveMarketCockpitService.build" in routes
    assert "durable_snapshots" in routes
    assert "RegionPerformanceService(" not in service
    assert "RegionMarketService(" not in service
    assert "db.session" not in service
    assert "unit_share_gap_to_national" in service
    assert "national_company_unit" in service
    assert "national_market_unit" in service
    assert "_regional_ai_insights" in service
    assert '"ai_insights"' in service
    assert '"target_tl": round(target_tl, 2)' in service
    assert '"actual_tl": actual_tl' in service
    assert '"company_unit": round(company_unit, 2)' in service
    assert '"competitor_unit": round(competitor_unit, 2)' in service
    assert '"market_unit": round(market_unit, 2)' in service


def test_market_analysis_loads_clarity_layer_last_and_removes_status_column():
    template = (ROOT / "app/templates/market_analysis.html").read_text(encoding="utf-8")
    readability = (ROOT / "app/static/css/market-analysis-readability.css").read_text(encoding="utf-8")
    clarity = (ROOT / "app/static/css/market-analysis-exec-clarity.css").read_text(encoding="utf-8")
    assert template.index("executive-market-cockpit.css") < template.index("market-analysis-readability.css")
    assert template.index("market-analysis-readability.css") < template.index("market-analysis-exec-clarity.css")
    assert ".market-source-copy span" in readability
    assert ".manager-region-button span" in readability
    assert ".exec-cockpit .exec-region-foot" in readability
    assert '[data-theme="dark"]' in readability
    assert ".market-analysis-hero h1{color:#fff!important" in readability
    assert ".market-analysis-table th:last-child,.market-analysis-table td:last-child{display:none}" not in readability
    assert "<th>Veri durumu</th>" not in template
    assert "item.data_status" not in template
    assert ".exec-cockpit .exec-hero h2" in clarity
    assert ".exec-overview-grid" in clarity
    assert ".exec-rival-overview" in clarity


def test_snapshot_backfill_has_application_root_on_python_path():
    installer = (ROOT / "deploy/install_systemd_service.sh").read_text(encoding="utf-8")
    assert 'PYTHONPATH="$ims_path${PYTHONPATH:+:$PYTHONPATH}"' in installer
    assert "scripts/backfill_active_region_snapshots.py" in installer
