from unittest import mock

import pandas as pd
from openpyxl import Workbook

from app.services.alias_service import AliasService
from app.services.semantic_import_discovery import (
    _competition_signature_from_frame,
    install_semantic_import_discovery,
)
from app.services.target_import_service import TargetImportService
from app.services.official_brick_spread_atomic import _discover_spread_sheet
from app.services.official_brick_spread_service import OfficialBrickSpreadService


def test_renamed_competition_sheet_is_discovered_from_content():
    products = [f"RAKIP URUN {index}" for index in range(1, 14)]
    frame = pd.DataFrame([
        ["Ocak Çıkış TL", None, *products],
        ["BÖLGE", "TTS ISMI", *(["TL"] * len(products))],
        ["101", "AYSE KAYA", *range(1, len(products) + 1)],
    ])
    assert _competition_signature_from_frame(frame) == "competition_tl"


def test_broad_brick_market_without_representative_header_is_competition():
    products = [f"RAKIP URUN {index}" for index in range(1, 21)]
    frame = pd.DataFrame([
        ["Aylık Kutu Raporu", None, *products],
        ["BÖLGE", "IAM BRICK", *(["KUTU"] * len(products))],
        ["101", "KADIKOY MERKEZ", *range(1, len(products) + 1)],
    ])
    assert _competition_signature_from_frame(frame) == "competition_box"


def test_small_company_sales_sheet_is_not_guessed_as_competition():
    frame = pd.DataFrame([
        ["BÖLGE", "TTS ISMI", "TRAVAZOL TL", "MONUROL TL"],
        ["101", "AYSE KAYA", 100, 200],
    ])
    assert _competition_signature_from_frame(frame) is None


def test_renamed_dedicated_target_sheet_is_discovered_from_content():
    install_semantic_import_discovery()
    frame = pd.DataFrame([
        ["Aylık plan", None, None, None],
        ["Temsilci", "Travazol Hedef TL", "Monurol Hedef TL", "Kutu"],
        ["Ayşe Kaya", 100, 200, 1],
    ])

    def fake_product(value):
        normalized = AliasService.normalize(value)
        if "TRAVAZOL" in normalized or "MONUROL" in normalized:
            return {"matched": True, "method": "EXACT", "object": object()}
        return {"matched": False, "method": "NONE", "object": None}

    service = TargetImportService("unused.xlsx", upload_id=1)
    with mock.patch.object(AliasService, "find_product", side_effect=fake_product):
        assert service._is_target_sheet("tamamen-yeni-bir-ad", frame) is True


def test_renamed_official_brick_spread_is_discovered_from_content():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "2028 yeni dağılım raporu"
    headers = ["BÖLGE", "TTS ISMI", "Brick Sayısı", "Travazol", "Monurol", "Acnemix", "Mixovul", "Stiderm", "Brimoder", "TOPLAM"]
    sheet.append(headers)
    sheet.append(["101", "AYSE KAYA", 10, 1, 2, 3, 4, 5, 6, 21])
    assert _discover_spread_sheet(OfficialBrickSpreadService, workbook) == sheet.title
