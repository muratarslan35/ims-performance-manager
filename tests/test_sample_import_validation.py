import tempfile
from pathlib import Path

import pytest

from validate_sample_import import DEFAULT_SAMPLE, run_validation


def test_real_sample_workbook_validation_passes():
    if not DEFAULT_SAMPLE.exists():
        pytest.skip("Real sample workbook is not included in this checkout")

    with tempfile.TemporaryDirectory() as temp_dir:
        db_url = f"sqlite:///{Path(temp_dir) / 'sample-validation.db'}"
        report = run_validation(db_url=db_url)

    assert report["success"] is True
    assert report["counts"]["ims_summary"] > 0
    assert report["counts"]["ims_summary_value_share_non_null"] > 0
    assert report["stage_metrics_count"] > 0
