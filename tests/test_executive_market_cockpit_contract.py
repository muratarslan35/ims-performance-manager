from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_executive_cockpit_is_below_region_workspace_and_dynamic():
    template = (ROOT / "app/templates/market_analysis.html").read_text(encoding="utf-8")
    partial = (ROOT / "app/templates/partials/executive_market_cockpit.html").read_text(encoding="utf-8")
    javascript = (ROOT / "app/static/js/executive-market-cockpit.js").read_text(encoding="utf-8")

    assert template.index('manager-region-cockpit') < template.index('executive_market_cockpit.html')
    assert "data-exec-period-button" in partial
    assert "11 Bölge Rekabet Haritası" in partial
    assert "Türkiye Ürün Portföy Matrisi" in partial
    assert "En Yüksek 5 Rakip Baskısı" in partial
    assert "Fırsat ve Risk Bölgeleri" in partial
    assert "Türkiye Realizasyon Trendi" in partial
    assert "GENEL MÜDÜR YÖNETİM ÖZETİ" in partial
    assert "Türkiye gerçekleşen" in partial
    assert "TR kutu payı farkı" in partial
    assert "region.share_gap_to_national" not in partial
    assert "region.unit_share_gap_to_national" in partial
    assert "openRegion" in javascript
    assert "Chart.getChart" in javascript


def test_executive_trend_renders_monthly_realization_labels():
    javascript = (ROOT / "app/static/js/executive-market-cockpit.js").read_text(encoding="utf-8")
    assert 'id: "execTrendValueLabels"' in javascript
    assert 'ctx.fillText(`%${Number(value).toLocaleString("tr-TR"' in javascript
    assert "plugins: [trendValueLabels]" in javascript
    assert "layout: {padding: {top: 18}}" in javascript


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


def test_market_analysis_loads_readability_layer_last():
    template = (ROOT / "app/templates/market_analysis.html").read_text(encoding="utf-8")
    css = (ROOT / "app/static/css/market-analysis-readability.css").read_text(encoding="utf-8")
    assert template.index("executive-market-cockpit.css") < template.index("market-analysis-readability.css")
    assert ".market-source-copy span" in css
    assert ".manager-region-button span" in css
    assert ".exec-cockpit .exec-region-foot" in css
    assert '[data-theme="dark"]' in css
    assert ".market-analysis-hero h1{color:#fff!important" in css
    assert ".market-analysis-table th:last-child,.market-analysis-table td:last-child{display:none}" in css
    assert ".exec-cockpit .exec-summary-items p{font-size:12px!important" in css


def test_snapshot_backfill_has_application_root_on_python_path():
    installer = (ROOT / "deploy/install_systemd_service.sh").read_text(encoding="utf-8")
    assert 'PYTHONPATH="$ims_path${PYTHONPATH:+:$PYTHONPATH}"' in installer
    assert "scripts/backfill_active_region_snapshots.py" in installer
