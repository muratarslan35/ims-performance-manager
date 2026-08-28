from pathlib import Path


def test_balance_unit_is_authoritative_unit_actual_source():
    source = Path("app/services/ims_import_service.py").read_text(encoding="utf-8")
    assert "actual_unit = float(target.unit_target or 0.0) - float(balance_unit)" in source
    assert "target.unit_realization = actual_unit" in source
    assert "summary.unit = actual_unit" in source
    assert "self._balance_unit_actual_keys.add((rep_id, product_id))" in source


def test_weekly_units_are_only_fallback_when_balance_units_are_missing():
    source = Path("app/services/ims_import_service.py").read_text(encoding="utf-8")
    assert 'if "unit" in metrics and (rep_id, product_id) not in self._balance_unit_actual_keys:' in source
