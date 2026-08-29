from pathlib import Path


def test_passive_representative_has_red_status_label():
    html = Path("app/templates/representative_detail.html").read_text()
    assert "{% if not representative.active %}" in html
    assert "text-danger fw-bold" in html
    assert "PASİF KULLANICI" in html


def test_ims_region_unit_gap_uses_db_target_units_and_official_actual_units():
    source = Path("app/services/region_performance_service.py").read_text()
    segment = source.split("def _official_region_unit_month", 1)[1].split("def aggregate", 1)[0]
    assert "func.sum(Target.unit_target)" in segment
    assert "ACTUAL_TYPE" in segment
    assert "actual_rows[product_id].unit" in segment
    assert "target.unit" not in segment
    assert "dashboard_balance_region" not in segment
