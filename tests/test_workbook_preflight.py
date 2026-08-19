import pandas as pd
import pytest

from app.services.workbook_preflight import WorkbookPreflight


class FakeService:
    REPRESENTATIVE_HEADERS = {"TEMSILCI", "TTS ISMI"}
    PRODUCT_GROUP_HEADERS = {"URUN", "PRODUCT"}
    REGION_HEADERS = {"BOLGE"}
    PROVINCE_HEADERS = {"IL"}
    NORMALIZED_SHEET_TYPES = {"TL": "tl", "KUTU": "unit"}

    def __init__(self, workbook):
        self.workbook = workbook
        self.statistics = {}
        self.parser_decisions = []

    @staticmethod
    def clean_text(value):
        if value is None or pd.isna(value):
            return ""
        return str(value).strip()

    def find_header_row(self, frame):
        for index in range(min(80, len(frame))):
            row = " ".join(str(v).upper() for v in frame.iloc[index].tolist())
            if "TEMSILCI" in row or "TTS ISMI" in row:
                return index
        return None


def test_manifest_counts_every_sheet_and_known_specialized_sheet():
    workbook = {
        "TTS ÇIKIŞLARI": pd.DataFrame([["Temsilci", "Ürün", "TL"], ["A B", "X", 1]]),
        "Satış Brick Yayılımı": pd.DataFrame([["Master"], [123]]),
        "BAKİYE": pd.DataFrame([["Hedef"], [10]]),
    }
    service = FakeService(workbook)
    manifest = WorkbookPreflight(service).validate()
    assert len(manifest) == 3
    assert service.statistics["manifest_sheet_count"] == 3
    assert service.statistics["manifest_verified_sheets"] == 3
    assert service.statistics["unclassified_sheet"] == 0


def test_unknown_meaningful_sheet_is_blocking():
    service = FakeService({"GİZLİ YENİ RAPOR": pd.DataFrame([["foo", "bar"], [1, 2]])})
    with pytest.raises(ValueError, match="sınıflandırılmamış sheet"):
        WorkbookPreflight(service).validate()
    assert service.statistics["unclassified_sheet"] == 1


def test_generic_header_self_heals_unknown_title():
    service = FakeService({"Yeni İsim": pd.DataFrame([["Temsilci", "Ürün", "TL"], ["A B", "X", 1]])})
    manifest = WorkbookPreflight(service).validate()
    assert manifest[0]["coverage"] == "generic_parser"
    assert manifest[0]["sheet_type"] == "representative_sales"


def test_empty_sheet_is_explicit_nondata_not_unknown():
    service = FakeService({"NOTLAR": pd.DataFrame([[None, None]])})
    manifest = WorkbookPreflight(service).validate()
    assert manifest[0]["coverage"] == "explicit_nondata"
    assert manifest[0]["sheet_type"] == "explicit_nondata"
