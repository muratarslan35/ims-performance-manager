from pathlib import Path


def test_representative_workspace_wires_market_reads_to_source_keyed_cache():
    source = Path("app/services/representative_period_workspace.py").read_text(encoding="utf-8")
    assert "RepresentativeAnalysisCache.get_or_compute(" in source
    assert "rep-market:" in source
    assert "RepresentativeMarketService(representative, y, m).build()" in source
    assert "previous_upload_id" in source
    assert "production_upload_id" in source
    assert "scope_digest" in source


def test_market_cache_change_does_not_replace_calculation_loader():
    source = Path("app/services/representative_period_workspace.py").read_text(encoding="utf-8")
    assert "ProductionResultService.effective_products" in source
    assert "realization_percent" in source
    assert "P2" not in source or "PRODUCTION_2" in source
