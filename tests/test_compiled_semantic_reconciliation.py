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


def test_compiled_scan_builds_column_context_once_per_column(monkeypatch):
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

    # Four source columns exist, two are dimensions; the two metric columns
    # are compiled once each rather than once per data row/cell.
    assert observations
    assert calls == 2
