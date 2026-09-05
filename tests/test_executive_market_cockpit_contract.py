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
    assert "En Yüksek 5 Rakip Hareketi" in partial
    assert "Fırsat ve Risk Bölgeleri" in partial
    assert "Türkiye Realizasyon Trendi" in partial
    assert "GENEL MÜDÜR YÖNETİM ÖZETİ" in partial
    assert "openRegion" in javascript
    assert "Chart.getChart" in javascript


def test_executive_read_model_reuses_durable_snapshot_payloads_without_db_queries():
    service = (ROOT / "app/services/executive_market_cockpit_service.py").read_text(encoding="utf-8")
    routes = (ROOT / "app/routes/__init__.py").read_text(encoding="utf-8")

    assert "performs no database queries" in service
    assert "ExecutiveMarketCockpitService.build" in routes
    assert "durable_snapshots" in routes
    assert "RegionPerformanceService(" not in service
    assert "RegionMarketService(" not in service
    assert "db.session" not in service


def test_snapshot_backfill_has_application_root_on_python_path():
    installer = (ROOT / "deploy/install_systemd_service.sh").read_text(encoding="utf-8")
    assert 'PYTHONPATH="$ims_path${PYTHONPATH:+:$PYTHONPATH}"' in installer
    assert "scripts/backfill_active_region_snapshots.py" in installer
