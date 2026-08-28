import inspect

import pandas as pd
import pytest

from app.services.workbook_preflight import WorkbookPreflight

class FakeService:
    REPRESENTATIVE_HEADERS={"TEMSILCI","TTS ISMI"};PRODUCT_GROUP_HEADERS={"URUN","PRODUCT"};REGION_HEADERS={"BOLGE"};PROVINCE_HEADERS={"IL"};NORMALIZED_SHEET_TYPES={"TL":"tl","KUTU":"unit"}
    def __init__(self,workbook):self.workbook=workbook;self.statistics={};self.parser_decisions=[]
    @staticmethod
    def clean_text(value):
        if value is None or pd.isna(value):return ""
        return str(value).strip()
    def find_header_row(self,frame):
        for index in range(min(80,len(frame))):
            row=" ".join(str(v).upper() for v in frame.iloc[index].tolist())
            if "TEMSILCI" in row or "TTS ISMI" in row:return index
        return None

def test_manifest_counts_every_sheet_and_known_specialized_sheet():
    workbook={"TTS ÇIKIŞLARI":pd.DataFrame([["Temsilci","Ürün","TL"],["A B","X",1]]),"Satış Brick Yayılımı":pd.DataFrame([["Master"],[123]]),"BAKİYE":pd.DataFrame([["Hedef"],[10]])}
    service=FakeService(workbook);manifest=WorkbookPreflight(service).validate()
    assert len(manifest)==3;assert service.statistics["manifest_sheet_count"]==3;assert service.statistics["manifest_verified_sheets"]==3;assert service.statistics["unclassified_sheet"]==0;assert service.statistics["unclassified_master_cell"]==0;assert service.statistics["manifest_meaningful_cells"]==10

def test_unknown_meaningful_sheet_is_blocking():
    service=FakeService({"GİZLİ YENİ RAPOR":pd.DataFrame([["foo","bar"],[1,2]])})
    with pytest.raises(ValueError,match="sınıflandırılmamış sheet"):WorkbookPreflight(service).validate()
    assert service.statistics["unclassified_sheet"]==1;assert service.statistics["unclassified_master_cell"]==4

def test_generic_header_self_heals_unknown_title():
    service=FakeService({"Yeni İsim":pd.DataFrame([["Temsilci","Ürün","TL"],["A B","X",1]])});manifest=WorkbookPreflight(service).validate()
    assert manifest[0]["coverage"]=="generic_parser";assert manifest[0]["sheet_type"]=="representative_sales";assert manifest[0]["classification_basis"]=="content";assert {cell["classification"] for cell in service.workbook_cell_ledger}=={"IMPORTED_FACT"}

def test_header_can_move_without_changing_sheet_identity():
    frame=pd.DataFrame([[None,None,None],["rapor notu",None,None],[None,None,None],["Temsilci","Ürün","TL"],["A B","X",0]])
    service=FakeService({"2027 yeni format satis raporu":frame});manifest=WorkbookPreflight(service).validate()
    assert manifest[0]["sheet_type"]=="representative_sales";assert manifest[0]["header_row"]==3;assert manifest[0]["classification_basis"]=="content"

def test_specialized_sheet_can_be_renamed_when_content_signature_is_stable():
    frame=pd.DataFrame([["Haftalık Çıkış","Ürün","Kutu"],["Bölge","X",0]])
    service=FakeService({"Rapor-42":frame});manifest=WorkbookPreflight(service).validate()
    assert manifest[0]["sheet_type"]=="weekly_sales";assert manifest[0]["coverage"]=="specialized_parser";assert manifest[0]["classification_basis"]=="content"

def test_sheet_order_does_not_affect_classification():
    first={"Rapor B":pd.DataFrame([["Bakiye","Hedef TL"],["A",0]]),"Rapor A":pd.DataFrame([["Temsilci","Ürün","TL"],["A","X",0]])}
    second=dict(reversed(list(first.items())))
    a={x["sheet_name"]:x["sheet_type"] for x in WorkbookPreflight(FakeService(first)).validate()};b={x["sheet_name"]:x["sheet_type"] for x in WorkbookPreflight(FakeService(second)).validate()}
    assert a==b

def test_empty_sheet_is_explicit_nondata_not_unknown():
    service=FakeService({"NOTLAR":pd.DataFrame([[None,None]])});manifest=WorkbookPreflight(service).validate()
    assert manifest[0]["coverage"]=="explicit_nondata";assert manifest[0]["sheet_type"]=="explicit_nondata";assert service.workbook_cell_ledger==[]

def test_zero_is_meaningful_and_never_classified_as_blank():
    service=FakeService({"TTS ÇIKIŞLARI":pd.DataFrame([["Temsilci","Ürün","Kutu"],["A B","X",0]])});WorkbookPreflight(service).validate();zero_cells=[cell for cell in service.workbook_cell_ledger if cell["row"]==2 and cell["column"]==3]
    assert len(zero_cells)==1;assert zero_cells[0]["classification"]=="IMPORTED_FACT";assert service.statistics["manifest_meaningful_cells"]==6

def test_specialized_and_derived_cells_receive_terminal_classes():
    service=FakeService({"Satış Brick Yayılımı":pd.DataFrame([["Master","Kutu"],["A",0]]),"PAZAR":pd.DataFrame([["Pivot","TL"],["A",10]]),"NATIONAL":pd.DataFrame([["Bölge","TL"],["TR",10]])});WorkbookPreflight(service).validate();classes={}
    for cell in service.workbook_cell_ledger:classes.setdefault(cell["sheet_name"],set()).add(cell["classification"])
    assert classes["Satış Brick Yayılımı"]=={"IMPORTED_MASTER"};assert classes["PAZAR"]=={"VERIFIED_DERIVED"};assert classes["NATIONAL"]=={"AGGREGATE_VERIFIED"};assert service.statistics["unclassified_master_cell"]==0


def test_cell_ledger_hot_loop_avoids_scalar_dataframe_iloc():
    source = inspect.getsource(WorkbookPreflight.build_cell_ledger)
    assert ".iloc[" not in source


def test_array_cell_scan_preserves_coordinates_blank_and_numeric_zero():
    frame = pd.DataFrame([["Temsilci", None, "Kutu"], ["A B", "", 0], [None, float("nan"), 5]])
    cells = list(WorkbookPreflight(FakeService({}))._iter_meaningful_cells(frame))
    assert cells == [(0, 0, "Temsilci"), (0, 2, "Kutu"), (1, 0, "A B"), (1, 2, 0), (2, 2, 5)]
