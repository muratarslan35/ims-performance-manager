from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label} anchor not found")
    return text.replace(old, new, 1)


p = Path("app/services/ims_import_service.py")
s = p.read_text(encoding="utf-8")
old_clear = '''    def clear_month(self, year, month):
        """Remove all IMS data for a calendar month (destructive; kept for backward compat)."""
        IMSFact.query.filter_by(year=year, month=month).delete(synchronize_session=False)
        IMSRawData.query.filter_by(year=year, month=month).delete(synchronize_session=False)
        IMSSummary.query.filter_by(year=year, month=month).delete(synchronize_session=False)
        db.session.flush()
'''
new_clear = old_clear + '''
    def clear_week_snapshot(self, year, month, week_number):
        """Replace one weekly snapshot while rebuilding current period-derived state.

        Weekly raw/fact history for other weeks is retained. Period-scoped target,
        summary and brick-assignment rows are rebuilt from the incoming cumulative
        workbook so representatives who moved to another team do not remain in the
        active month simply because they existed in an earlier workbook.
        """
        self.clear_week(year, week_number)
        IMSSummary.query.filter_by(year=year, month=month).delete(synchronize_session=False)
        Target.query.filter_by(year=year, month=month).delete(synchronize_session=False)
        RepresentativeBrickAssignment.query.filter_by(year=year, month=month).delete(synchronize_session=False)
        db.session.flush()
'''
s = replace_once(s, old_clear, new_clear, "clear_month")
old_run = '''            if clear_before_import and week_number is None:
                self.clear_month(year, month)
            self.process_workbook(year, month, week_number=week_number)
'''
new_run = '''            if clear_before_import:
                if week_number is None:
                    self.clear_month(year, month)
                else:
                    self.clear_week_snapshot(year, month, week_number)
            self.process_workbook(year, month, week_number=week_number)
'''
s = replace_once(s, old_run, new_run, "run replace")
p.write_text(s, encoding="utf-8")

p = Path("app/services/region_performance_service.py")
s = p.read_text(encoding="utf-8")
old_region = '''        self.representatives = Representative.query.filter(
            or_(
                Representative.region == self.region_key,
                Representative.city == self.region_key,
                Representative.territory == self.region_key,
            ),
        ).order_by(Representative.rep_name.asc()).all()
        if not self.representatives:
            raise ValueError("Bölge bulunamadı.")
        self.rep_ids = [item.id for item in self.representatives]
'''
new_region = '''        master_representatives = Representative.query.filter(
            or_(
                Representative.region == self.region_key,
                Representative.city == self.region_key,
                Representative.territory == self.region_key,
            ),
        ).order_by(Representative.rep_name.asc()).all()
        if not master_representatives:
            raise ValueError("Bölge bulunamadı.")

        # Representative master history intentionally retains people who moved
        # between teams. The current month's Target rows form the active IMS
        # roster snapshot after a replace import. Use that scope for region
        # detail/market calculations whenever it is available.
        master_ids = [item.id for item in master_representatives]
        period_rep_ids = {
            int(row[0])
            for row in db.session.query(Target.representative_id).filter(
                Target.year == self.year,
                Target.month == self.month,
                Target.representative_id.in_(master_ids),
            ).distinct().all()
            if row[0] is not None
        }
        self.representatives = (
            [item for item in master_representatives if item.id in period_rep_ids]
            if period_rep_ids else master_representatives
        )
        self.rep_ids = [item.id for item in self.representatives]
'''
s = replace_once(s, old_region, new_region, "region roster")
p.write_text(s, encoding="utf-8")

Path("tests/test_weekly_snapshot_replace_contract.py").write_text(
    '''from pathlib import Path


def test_weekly_replace_rebuilds_period_derived_state_and_keeps_other_weeks():
    source = Path("app/services/ims_import_service.py").read_text(encoding="utf-8")
    start = source.index("def clear_week_snapshot(self, year, month, week_number):")
    end = source.index("def clear_month", start) if "def clear_month" in source[start + 1:] else source.index("def run", start)
    block = source[start:end]
    assert "self.clear_week(year, week_number)" in block
    assert "Target.query.filter_by(year=year, month=month).delete" in block
    assert "IMSSummary.query.filter_by(year=year, month=month).delete" in block
    assert "RepresentativeBrickAssignment.query.filter_by(year=year, month=month).delete" in block
    assert "IMSFact.query.filter_by(year=year, month=month).delete" not in block


def test_replace_flag_is_honored_for_numbered_week():
    source = Path("app/services/ims_import_service.py").read_text(encoding="utf-8")
    run = source[source.index("def run(self, year, month, clear_before_import=False, week_number=None):"):]
    assert "if clear_before_import:" in run
    assert "self.clear_week_snapshot(year, month, week_number)" in run
    assert "if clear_before_import and week_number is None" not in run


def test_region_detail_uses_current_period_target_roster_when_available():
    source = Path("app/services/region_performance_service.py").read_text(encoding="utf-8")
    start = source.index("def __init__")
    end = source.index("@staticmethod", start)
    block = source[start:end]
    assert "period_rep_ids" in block
    assert "Target.year == self.year" in block
    assert "Target.month == self.month" in block
    assert "if period_rep_ids else master_representatives" in block
''',
    encoding="utf-8",
)
