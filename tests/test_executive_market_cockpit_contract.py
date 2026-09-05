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
    assert "Güncel kutu pazar payı" in partial
    assert "Seçili dönem realizasyonu" in partial
    assert "Şirket kutu çıkışı" in partial
    assert "Bölgesel AI Yönetim İçgörüleri" in partial
    assert "GERÇEK VERİ + DİNAMİK YAPAY ZEKA" in partial
    assert "Dönem hedefi" in partial
    assert "Dönem gerçekleşen" in partial
    assert "Rakip kutu" in partial
    assert "Toplam kutu pazar" in partial
    assert "AI yönetim yorumu" in partial
    assert "data-exec-ai-panel" in partial
    assert "region.share_gap_to_national" not in partial
    assert "region.unit_share_gap_to_national" in partial
    assert "openRegion" in javascript
    assert "Chart.getChart" in javascript
    assert "panel.dataset.execAiPanel === key" in javascript


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
    assert ".exec-metric-guide" in clarity
    assert ".exec-ai-section" in clarity
    assert ".exec-ai-facts" in readability


def test_snapshot_backfill_has_application_root_on_python_path():
    installer = (ROOT / "deploy/install_systemd_service.sh").read_text(encoding="utf-8")
    assert 'PYTHONPATH="$ims_path${PYTHONPATH:+:$PYTHONPATH}"' in installer
    assert "scripts/backfill_active_region_snapshots.py" in installer
