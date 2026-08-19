import pytest

from app.services.derived_master_verification import apply_derived_verification_gate


class FakeImporter:
    def __init__(self, evidence=None):
        self.statistics = {"unclassified_master_cell": 0}
        self.workbook_cell_ledger = [
            {"sheet_name": "PAZAR", "row": 2, "column": 3, "classification": "VERIFIED_DERIVED", "sheet_type": "master_pivot_derived"},
            {"sheet_name": "TTS ÇIKIŞLARI", "row": 2, "column": 3, "classification": "IMPORTED_FACT", "sheet_type": "representative_sales"},
        ]
        self.derived_verification_evidence = evidence or {}


def test_derived_cell_without_value_evidence_blocks_upload():
    importer = FakeImporter()
    with pytest.raises(ValueError, match="değer-seviyesi master kanıtı yok"):
        apply_derived_verification_gate(importer)
    assert importer.statistics["unverified_derived_cells"] == 1
    assert importer.statistics["unclassified_master_cell"] == 1
    assert importer.workbook_cell_ledger[0]["classification"] == "UNCLASSIFIED_MASTER_CELL"


def test_derived_cell_with_matching_evidence_passes():
    evidence = {("PAZAR", 2, 3): {"matched": True, "source_sheet": "TTS ÇIKIŞLARI", "source_value": 0, "derived_value": 0}}
    importer = FakeImporter(evidence)
    result = apply_derived_verification_gate(importer)
    assert result == {"verified": 1, "unverified": 0}
    assert importer.statistics["verified_derived_cells"] == 1
    assert importer.statistics["unclassified_master_cell"] == 0
    assert importer.workbook_cell_ledger[0]["verification"]["derived_value"] == 0
