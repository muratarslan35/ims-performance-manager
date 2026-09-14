from app.services.ims_import_service import IMSImportService


def test_week_parser_accepts_separator_variants():
    assert IMSImportService.extract_week_number("Tayfun-1_33._Hafta_Agustos.xlsx") == 33
    assert IMSImportService.extract_week_number("Tayfun-1_32.Hafta_Agustos.xlsx") == 32
    assert IMSImportService.extract_week_number("31 Hafta Temmuz.xlsx") == 31
    assert IMSImportService.extract_week_number("30-Hafta.xlsx") == 30
