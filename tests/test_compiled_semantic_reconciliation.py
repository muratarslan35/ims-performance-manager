from types import SimpleNamespace

import pandas as pd

from app.services.compiled_import_semantic_reconciliation import (
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
    # observation plan then reads the two metric columns once. Four data rows
    # do not add any further column-context work.
    assert observations
    assert calls == 6


def test_weekly_trend_headers_keep_products_weeks_and_subtotals_distinct():
    frame = pd.DataFrame(
        [
            [None] * 13,
            [None, None, "TRAVAZOL KREM", None, None, None, "TRAVAZOL KREM Subtotal", None,
             "MONUROL SASE", None, None, None, "MONUROL SASE Subtotal"],
            [None, None, "Week 26/40 (28.09.26-04.10.26)", None,
             "Week 26/41 (05.10.26-11.10.26)", None, None, None,
             "Week 26/40 (28.09.26-04.10.26)", None,
             "Week 26/41 (05.10.26-11.10.26)", None, None],
            ["AREAS", "SUBTERRITORIES", "UNITS REPORT", "VALUES REPORT",
             "UNITS REPORT", "VALUES REPORT", "UNITS REPORT", "VALUES REPORT",
             "UNITS REPORT", "VALUES REPORT", "UNITS REPORT", "VALUES REPORT",
             "UNITS REPORT"],
            ["ANKARA", "ENGIN YAPAK", 1339.0, 128438.31, 578.0, 56199.78, 1917.0, 184638.09,
             442.0, 43861.69, 582.0, 56809.42, 1024.0],
        ]
    )
    importer = SimpleNamespace(
        workbook={"5-EKİP HAFTALIK TREND ": frame},
        workbook_manifest=[
            {
                "sheet_name": "5-EKİP HAFTALIK TREND ",
                "coverage": "data",
                "sheet_type": "master_pivot_derived",
                "header_row": 3,
            }
        ],
        statistics={},
        workbook_cell_ledger=[],
    )

    base_observations, _ = WorkbookSemanticReconciler(importer)._observations()
    fast_observations, _ = CompiledWorkbookSemanticReconciler(importer)._observations()

    assert fast_observations == base_observations
    assert len({item["semantic_key"] for item in fast_observations}) == len(fast_observations)

    result = CompiledWorkbookSemanticReconciler(importer).reconcile()
    assert result["conflicts"] == 0
    assert importer.statistics["duplicate_conflict"] == 0

    by_coordinate = {(item["row"], item["column"]): item for item in fast_observations}
    week40_travazol = by_coordinate[(5, 3)]
    week41_travazol = by_coordinate[(5, 5)]
    week40_monurol = by_coordinate[(5, 9)]
    travazol_subtotal = by_coordinate[(5, 7)]

    assert week40_travazol["period_scope"].startswith("weekly:")
    assert week40_travazol["period_scope"] != week41_travazol["period_scope"]
    assert week40_travazol["product_key"] == "TRAVAZOL KREM"
    assert week40_monurol["product_key"] == "MONUROL SASE"
    assert travazol_subtotal["period_scope"] == "aggregate"
    assert travazol_subtotal["product_key"] == "__SUBTOTAL__:TRAVAZOL KREM"
