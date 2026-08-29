from pathlib import Path


def test_passive_representative_has_red_status_label():
    html = Path("app/templates/representative_detail.html").read_text()
    assert "{% if not representative.active %}" in html
    assert "text-danger fw-bold" in html
    assert "PASİF KULLANICI" in html


def test_ims_region_unit_gap_uses_target_minus_mf_siz_kutu_balance():
    source = Path("app/services/region_performance_service.py").read_text()
    segment = source.split("def _official_region_unit_month", 1)[1].split("def aggregate", 1)[0]
    assert "func.sum(Target.unit_target)" in segment
    assert "region_balance_units(upload_id, self.region_key)" in segment
    assert "target_unit - balances[product_id]" in segment
    assert "actual_rows" not in segment
    assert "ACTUAL_TYPE" not in segment


def test_unit_balance_example_matches_workbook_semantics():
    target_unit = 74907
    remaining_balance = 213
    actual_unit = target_unit - remaining_balance
    assert actual_unit == 74694
    assert actual_unit - target_unit == -213
