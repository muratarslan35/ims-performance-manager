from pathlib import Path

path = Path("app/services/ims_import_service.py")
text = path.read_text(encoding="utf-8")

old = "        self._brick_assignment_cache = {}\n"
new = old + "        self._balance_unit_actual_keys = set()\n"
assert text.count(old) == 1, text.count(old)
text = text.replace(old, new, 1)

old = """                summary = summaries.get((rep_id, product_id))
                if summary is not None:
                    summary.target_tl = target.tl_target
                    summary.target_unit = target.unit_target
"""
new = """                summary = summaries.get((rep_id, product_id))
                if balance_unit is not None:
                    # BAKİYE / MF'siz KUTU BAKİYE is the remaining box count.
                    # Representative IMS box output therefore equals approved
                    # box target minus the workbook's remaining box balance.
                    actual_unit = float(target.unit_target or 0.0) - float(balance_unit)
                    target.unit_realization = actual_unit
                    self._balance_unit_actual_keys.add((rep_id, product_id))
                    if summary is not None:
                        summary.unit = actual_unit
                if summary is not None:
                    summary.target_tl = target.tl_target
                    summary.target_unit = target.unit_target
"""
assert text.count(old) == 1, text.count(old)
text = text.replace(old, new, 1)

old = """                if \"unit\" in metrics:
                    summary.unit = metrics[\"unit\"]
                    if target is not None:
                        target.unit_realization = metrics[\"unit\"]
"""
new = """                if \"unit\" in metrics and (rep_id, product_id) not in self._balance_unit_actual_keys:
                    # Fallback only for legacy workbooks without MF'siz KUTU
                    # BAKİYE. When balance exists, target - balance is the
                    # authoritative representative IMS box output.
                    summary.unit = metrics[\"unit\"]
                    if target is not None:
                        target.unit_realization = metrics[\"unit\"]
"""
assert text.count(old) == 1, text.count(old)
text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")

Path("tests/test_balance_unit_actual_source_contract.py").write_text(
    '''from pathlib import Path\n\n\ndef test_balance_unit_is_authoritative_unit_actual_source():\n    source = Path("app/services/ims_import_service.py").read_text(encoding="utf-8")\n    assert "actual_unit = float(target.unit_target or 0.0) - float(balance_unit)" in source\n    assert "target.unit_realization = actual_unit" in source\n    assert "summary.unit = actual_unit" in source\n    assert "self._balance_unit_actual_keys.add((rep_id, product_id))" in source\n\n\ndef test_weekly_units_are_only_fallback_when_balance_units_are_missing():\n    source = Path("app/services/ims_import_service.py").read_text(encoding="utf-8")\n    assert 'if "unit" in metrics and (rep_id, product_id) not in self._balance_unit_actual_keys:' in source\n''',
    encoding="utf-8",
)
