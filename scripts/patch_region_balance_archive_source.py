from pathlib import Path

path = Path('app/services/region_performance_service.py')
source = path.read_text()
import_anchor = 'from app.services.production_result_service import ProductionResultService\n'
if 'region_balance_unit_service' not in source:
    source = source.replace(import_anchor, import_anchor + 'from app.services.region_balance_unit_service import region_balance_units\n', 1)
old = '''        balances = {
            product_id: Decimal(str(balance_unit or 0))
            for product_id, balance_unit in db.session.query(
                IMSRawData.product_id, IMSRawData.unit
            ).filter(
                IMSRawData.upload_id == upload_id,
                IMSRawData.sheet_type == "dashboard_balance_region",
                IMSRawData.territory == self.region_key,
            ).all()
        }
        if not balances:
            return {}

        return {
            product_id: [
                target_unit,
                target_unit - balances[product_id],
                True,
            ]
            if product_id in balances
            else [target_unit, Decimal("0"), False]
            for product_id, target_unit in target_units.items()
        }
'''
new = '''        balances = {
            int(product_id): Decimal(str(value))
            for product_id, value in region_balance_units(upload_id, self.region_key).items()
        }
        if not balances:
            # Legacy archives may be unavailable. Fail closed and allow the
            # aggregate layer to use its existing representative fallback.
            return {}

        return {
            product_id: [
                target_unit,
                target_unit - balances[product_id],
                True,
            ]
            if product_id in balances
            else [target_unit, Decimal("0"), False]
            for product_id, target_unit in target_units.items()
        }
'''
if old not in source:
    raise SystemExit('target balance block not found')
path.write_text(source.replace(old, new, 1))

contract = Path('tests/test_passive_user_and_region_unit_gap_contract.py')
text = contract.read_text()
text = text.replace('assert "dashboard_balance_region" in segment\n    assert "IMSRawData.unit" in segment\n', 'assert "region_balance_units(upload_id, self.region_key)" in segment\n')
contract.write_text(text)

region_test = Path('tests/test_region_read_v2.py')
text = region_test.read_text()
text = text.replace('def test_region_product_unit_gap_uses_mf_siz_kutu_balance_not_actual_aggregate(tmp_path):', 'def test_region_product_unit_gap_uses_archived_mf_siz_kutu_balance_not_actual_aggregate(tmp_path, monkeypatch):')
needle = '        db.session.commit()\n        row = RegionPerformanceService("901", 2026, 2).report()["periods"]["monthly"]["products"][0]\n        assert row["target_unit"] == Decimal("100.0")\n        assert row["actual_unit"] == Decimal("88.0")\n'
repl = '        db.session.commit()\n        monkeypatch.setattr("app.services.region_performance_service.region_balance_units", lambda upload_id, region_key: {product.id: 12.0})\n        row = RegionPerformanceService("901", 2026, 2).report()["periods"]["monthly"]["products"][0]\n        assert row["target_unit"] == Decimal("100.0")\n        assert row["actual_unit"] == Decimal("88.0")\n'
if needle not in text:
    raise SystemExit('region regression anchor missing')
region_test.write_text(text.replace(needle, repl, 1))
