from pathlib import Path


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
