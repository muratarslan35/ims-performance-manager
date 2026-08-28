from types import SimpleNamespace

import pandas as pd

from app.services.compiled_workbook_semantic_reconciliation import (
    CompiledWorkbookSemanticReconciler,
)
from app.services.workbook_semantic_reconciliation import WorkbookSemanticReconciler


def _importer():
    frame = pd.DataFrame(
        [
            ["TERRITORIES", "SUBTERRITORIES", "VALUES REPORT", "VALUES REPORT"],
            ["TERRITORIES", "SUBTERRITORIES", "TRAVAZOL", "MONUROL"],
            ["101 ISTANBUL", "BRICK A", 10.0, 20.0],
            ["101 ISTANBUL", "BRICK B", 0.0, None],
            ["101 ISTANBUL", "BRICK C", 30.0, 40.0],
            ["101 ISTANBUL", "BRICK D", 50.0, 60.0],
        ]
    )
    return SimpleNamespace(
        workbook={"RENAMED MONTHLY VALUE": frame},
        workbook_manifest=[
            {
                "sheet_name": "RENAMED MONTHLY VALUE",
                "coverage": "data",
                "sheet_type": "competition_tl",
                "header_row": 1,
            }
        ],
    )


def test_compiled_observation_scan_matches_base_semantics_and_preserves_zero():
    importer = _importer()
    base_observations, base_profiles = WorkbookSemanticReconciler(importer)._observations()
    fast_observations, fast_profiles = CompiledWorkbookSemanticReconciler(importer)._observations()

    assert fast_profiles == base_profiles
    assert fast_observations == base_observations
    assert any(item["value"] == 0.0 for item in fast_observations)


def test_compiled_scan_column_context_cost_does_not_scale_with_data_rows(monkeypatch):
    importer = _importer()
    service = CompiledWorkbookSemanticReconciler(importer)
    calls = 0
    original = service._column_context

    def counted(matrix, column):
        nonlocal calls
        calls += 1
        return original(matrix, column)

    monkeypatch.setattr(service, "_column_context", counted)
    observations, _ = service._observations()

    # Dimension discovery reads each of the four columns once; the compiled
    # observation plan then reads the two metric columns once.  Four data rows
    # do not add any further column-context work.
    assert observations
    assert calls == 6
