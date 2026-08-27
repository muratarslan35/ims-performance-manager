import pandas as pd
import pytest

from app.services.compiled_competition_import_service import CompiledCompetitionImportService
from app.services.competition_import_service import CompetitionImportService


SHEET = "AYLIK REKABET KUTU"


def _frame(second_value=12.5, duplicate_value=None):
    rows = [
        [None, None, None, None, None, None],
        [None, None, None, None, "GRUP A", "GRUP A"],
        ["REGION", "IAM BRICK", "TTS ISMI", "2 TTS ISMI", "ÜRÜN A", "ÜRÜN B"],
        [None, None, None, None, None, None],
        ["901 DIYARBAKIR", "MARDIN BATI", "TEM SILCI", "MUDUR", 0, second_value],
    ]
    if duplicate_value is not None:
        rows.append([None, "MARDIN BATI", "TEM SILCI", "MUDUR", 0, duplicate_value])
    return pd.DataFrame(rows)


class CapturingCompiledService(CompiledCompetitionImportService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.persisted = []

    def _existing_sheet_values(self, _norm_sheet_name):
        return {}

    def bulk_insert(self, model_mappings):
        self.persisted.extend(dict(item) for item in model_mappings)
        return len(model_mappings)


def _base_mappings(frame):
    service = CompetitionImportService(
        file_path="prepared.xlsx",
        upload_id=1,
        year=2026,
        month=2,
        workbook={SHEET: frame},
    )
    structure = service._parse_sheet_structure(SHEET)
    return [
        service._mapping_from_normalized_record(service.normalize_record(record), SHEET)
        for record in service._iter_sheet_records(structure)
    ]


def _fast_result(frame):
    service = CapturingCompiledService(
        file_path="prepared.xlsx",
        upload_id=1,
        year=2026,
        month=2,
        workbook={SHEET: frame},
    )
    structure = service._parse_sheet_structure(SHEET)
    stats = service._import_compiled_sheet(structure, SHEET)
    return service, stats


def test_compiled_fast_path_matches_standard_mapping_and_preserves_real_zero():
    frame = _frame()
    expected = _base_mappings(frame)
    service, stats = _fast_result(frame)

    assert service.persisted == expected
    assert stats["inserted"] == len(expected) == 2
    assert stats["duplicates"] == 0
    assert [item["metric_value"] for item in service.persisted] == [0.0, 12.5]
    assert service.parse_statistics["numeric_cells"] == 2


def test_compiled_fast_path_keeps_identical_duplicate_semantics():
    service, stats = _fast_result(_frame(12.5, duplicate_value=12.5))

    # Two products on the first row plus only one new key on the second row;
    # the repeated values are recognized as duplicates rather than reinserted.
    assert stats["inserted"] == 2
    assert stats["duplicates"] == 2
    assert len(service.persisted) == 2


def test_compiled_fast_path_fails_closed_on_conflicting_duplicate():
    with pytest.raises(ValueError, match="çelişen değerler"):
        _fast_result(_frame(12.5, duplicate_value=99.0))


def test_compiled_metric_parser_distinguishes_blank_zero_and_invalid():
    parse = CompiledCompetitionImportService._parse_metric_value
    assert parse(None) == (False, None, None)
    assert parse("-") == (False, None, None)
    assert parse(0) == (True, 0.0, None)
    assert parse("12,5%") == (True, 0.125, None)
    observed, value, invalid = parse("bozuk")
    assert observed is True
    assert value is None
    assert invalid == "bozuk"
