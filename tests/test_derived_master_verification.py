import pandas as pd
import pytest

from app.services.derived_master_verification import apply_derived_verification_gate


PRODUCTS = ["URUN A", "URUN B", "URUN C", "URUN D"]


def _source_frame():
    rows = [
        [None, None, *PRODUCTS],
        ["TERRITORIES", "SUBTERRITORIES", *(["VALUES REPORT"] * len(PRODUCTS))],
    ]
    for index in range(5):
        rows.append(["101 REGION", f"BRICK {index}", 0 if index == 0 else 100 + index, 200 + index, 300 + index, 400 + index])
    return pd.DataFrame(rows)


def _derived_frame(*, changed=False, missing=False, reordered=False):
    products = list(reversed(PRODUCTS)) if reordered else list(PRODUCTS)
    rows = [
        ["PivotTable42", None, *([None] * len(products))],
        ["Months = Jan 2026", None, *([None] * len(products))],
        [None, None, *products],
        ["TERRITORIES", "SUBTERRITORIES", *(["VALUES REPORT"] * len(products))],
    ]
    source = _source_frame()
    product_to_col = {name: 2 + PRODUCTS.index(name) for name in PRODUCTS}
    for index in range(5):
        values = [source.iloc[index + 2, product_to_col[name]] for name in products]
        if changed and index == 4:
            values[-1] = float(values[-1]) + 9.0
        if missing and index == 4:
            values[-1] = None
        rows.append(["101 REGION", f"BRICK {index}", *values])
    return pd.DataFrame(rows)


class FakeImporter:
    def __init__(self, derived=None, include_source=True):
        self.statistics = {"unclassified_master_cell": 0, "conflicting_match": 0, "duplicate_conflict": 0}
        self.workbook = {}
        self.workbook_manifest = []
        if include_source:
            self.workbook["authoritative-source"] = _source_frame()
            self.workbook_manifest.append({"sheet_name": "authoritative-source", "sheet_type": "competition_tl", "coverage": "specialized_parser", "header_row": 1})
        self.workbook["renamed-pivot-anything"] = derived if derived is not None else _derived_frame()
        self.workbook_manifest.append({"sheet_name": "renamed-pivot-anything", "sheet_type": "master_pivot_derived", "coverage": "specialized_parser", "header_row": 3})
        self.workbook_cell_ledger = []
        for sheet_name, frame in self.workbook.items():
            default = "VERIFIED_DERIVED" if sheet_name == "renamed-pivot-anything" else "IMPORTED_MASTER"
            for row in range(frame.shape[0]):
                for col in range(frame.shape[1]):
                    value = frame.iloc[row, col]
                    if value is None or (isinstance(value, float) and pd.isna(value)):
                        continue
                    self.workbook_cell_ledger.append({"sheet_name": sheet_name, "row": row + 1, "column": col + 1, "classification": default, "sheet_type": "master_pivot_derived" if default == "VERIFIED_DERIVED" else "competition_tl"})


def test_semantic_relationship_verifies_values_including_zero_without_coordinate_identity():
    importer = FakeImporter(derived=_derived_frame(reordered=True))
    result = apply_derived_verification_gate(importer)
    assert result["verified_derived_cells"] == 20
    assert result["conflicts"] == 0
    assert importer.statistics["unclassified_master_cell"] == 0
    zero_cells = [cell for cell in importer.workbook_cell_ledger if cell["sheet_name"] == "renamed-pivot-anything" and cell.get("verification", {}).get("derived_value") == 0]
    assert zero_cells


def test_one_conflicting_master_value_blocks_upload():
    importer = FakeImporter(derived=_derived_frame(changed=True))
    with pytest.raises(ValueError, match="semantic reconciliation başarısız"):
        apply_derived_verification_gate(importer)
    assert importer.statistics["conflicting_match"] >= 1


def test_one_missing_expected_derived_metric_blocks_upload():
    importer = FakeImporter(derived=_derived_frame(missing=True))
    with pytest.raises(ValueError, match="semantic reconciliation başarısız"):
        apply_derived_verification_gate(importer)
    assert importer.statistics["conflicting_match"] >= 1


def test_pivot_without_upstream_equivalent_is_retained_as_explicit_master_not_guessed():
    importer = FakeImporter(include_source=False)
    result = apply_derived_verification_gate(importer)
    assert result["verified_derived_cells"] == 0
    assert result["independent_master_cells"] == 20
    metric_cells = [cell for cell in importer.workbook_cell_ledger if cell["sheet_name"] == "renamed-pivot-anything" and cell["row"] >= 5]
    assert all(cell["classification"] == "IMPORTED_MASTER" for cell in metric_cells)


def test_header_and_metadata_cells_are_explicit_nondata_not_fake_derived_metrics():
    importer = FakeImporter()
    apply_derived_verification_gate(importer)
    headers = [cell for cell in importer.workbook_cell_ledger if cell["sheet_name"] == "renamed-pivot-anything" and cell["row"] <= 4]
    assert headers
    assert all(cell["classification"] == "EXPLICIT_NONDATA" for cell in headers)
