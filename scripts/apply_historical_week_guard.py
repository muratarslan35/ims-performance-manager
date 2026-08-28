from pathlib import Path

p = Path('app/services/ims_import_service.py')
s = p.read_text(encoding='utf-8')
old_clear = '''        self.clear_week(year, week_number)\n        IMSSummary.query.filter_by(year=year, month=month).delete(synchronize_session=False)\n        Target.query.filter_by(year=year, month=month).delete(synchronize_session=False)\n        RepresentativeBrickAssignment.query.filter_by(year=year, month=month).delete(synchronize_session=False)\n        db.session.flush()\n'''
new_clear = '''        self.clear_week(year, week_number)\n        # Replaying an older historical week must not erase the current\n        # month-to-date snapshot published by a later completed week.\n        if self._is_current_week_snapshot(year, month, week_number):\n            IMSSummary.query.filter_by(year=year, month=month).delete(synchronize_session=False)\n            Target.query.filter_by(year=year, month=month).delete(synchronize_session=False)\n            RepresentativeBrickAssignment.query.filter_by(year=year, month=month).delete(synchronize_session=False)\n        db.session.flush()\n'''
if old_clear not in s:
    raise SystemExit('clear snapshot anchor not found')
s = s.replace(old_clear, new_clear, 1)

old_assign = '''        with self._measure_stage("assignments_and_targets"):\n            self.sync_brick_assignments(year, month, prepared_sheets=wide_sheets)\n            if publish_period_snapshot:\n                TargetImportService(\n                    file_path=self.file_path,\n                    upload_id=self.upload.id,\n                    workbook=self.workbook,\n                ).run(\n                    year=year,\n                    month=month,\n                )\n            else:\n                self.warnings.append(\n                    f"{week_number}. hafta yeniden işlendi; daha yeni haftanın dönem hedef/realizasyon özeti korundu."\n                )\n'''
new_assign = '''        with self._measure_stage("assignments_and_targets"):\n            if publish_period_snapshot:\n                self.sync_brick_assignments(year, month, prepared_sheets=wide_sheets)\n                TargetImportService(\n                    file_path=self.file_path,\n                    upload_id=self.upload.id,\n                    workbook=self.workbook,\n                ).run(\n                    year=year,\n                    month=month,\n                )\n            else:\n                self.warnings.append(\n                    f"{week_number}. hafta yeniden işlendi; daha yeni haftanın dönem hedef/realizasyon/kadro özeti korundu."\n                )\n'''
if old_assign not in s:
    raise SystemExit('assignment stage anchor not found')
s = s.replace(old_assign, new_assign, 1)
p.write_text(s, encoding='utf-8')

p = Path('tests/test_weekly_snapshot_replace_contract.py')
t = p.read_text(encoding='utf-8')
t = t.replace(
    '    assert "Target.query.filter_by(year=year, month=month).delete" in block\n',
    '    assert "if self._is_current_week_snapshot(year, month, week_number):" in block\n    assert "Target.query.filter_by(year=year, month=month).delete" in block\n',
    1,
)
t += '''\n\ndef test_historical_week_does_not_publish_period_roster_or_targets():\n    source = Path("app/services/ims_import_service.py").read_text(encoding="utf-8")\n    start = source.index('with self._measure_stage("assignments_and_targets")')\n    end = source.index('with self._measure_stage("facts_summary_and_official_aggregates")', start)\n    block = source[start:end]\n    guard = block.index("if publish_period_snapshot:")\n    sync = block.index("self.sync_brick_assignments")\n    target = block.index("TargetImportService(")\n    else_pos = block.index("else:")\n    assert guard < sync < target < else_pos\n    assert "dönem hedef/realizasyon/kadro özeti korundu" in block\n'''
p.write_text(t, encoding='utf-8')
