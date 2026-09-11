import pandas as pd
import pytest

from app.services.kpi_workbook_compat import (
    build_canonical_brick_frame,
    is_product_kpi_sheet,
    validate_product_kpi_sheets,
)


def _matrix(metric, rows=None):
    phase = "TL" if metric == "tl" else "KUTU"
    return pd.DataFrame([
        ["1-9 AĞUSTOS", None, None, None, None, None, None, None, None, None, None],
        ["32.HAFTA", None, None, None, None, "TOPLAM", None, None, "TRAVAZOL", None, None],
        [None, None, None, "1.TTS", "2.TTS", "EKİP HEDEF", "EKİP ÇIKIŞ", "EKİP REAL", "ÜRÜN HEDEF", "ÜRÜN ÇIKIŞ", "REAL"],
        ["BÖLGE", "İL", "NATIONAL", "NATIONAL", "", 100, 40, 40, 80, 30, 37.5],
        ["101 ISTANBUL", "EDİRNE", "EDİRNE MERKEZ", "AYŞE TEST", "", 10, 4, 40, 8, rows if rows is not None else (300 if phase == "TL" else 3), 37.5],
    ])


def test_new_kpi_layout_joins_tl_and_unit_by_stable_brick_identity():
    workbook = {
        "2-TTS-BRİCK TL-REA%": _matrix("tl"),
        "2-TTS-BRİCK KUTU-REA%": _matrix("unit"),
    }
    frame, consumed = build_canonical_brick_frame(workbook)

    assert consumed == set(workbook)
    assert frame.columns.tolist() == [
        "BÖLGE", "İL", "IAM BRICK", "1 TTS ISMI", "2 TTS ISMI",
        "TRAVAZOL KUTU ÇIKIŞ", "TRAVAZOL TL ÇIKIŞ",
    ]
    assert frame.iloc[1]["TRAVAZOL KUTU ÇIKIŞ"] == 3
    assert frame.iloc[1]["TRAVAZOL TL ÇIKIŞ"] == 300


def test_new_kpi_layout_fails_closed_when_paired_rows_differ():
    unit = _matrix("unit")
    unit.iloc[4, 2] = "BAŞKA BRICK"
    with pytest.raises(ValueError, match="satırları eşleşmiyor"):
        build_canonical_brick_frame({
            "2-TTS-BRİCK TL-REA%": _matrix("tl"),
            "2-TTS-BRİCK KUTU-REA%": unit,
        })


def test_legacy_workbook_is_not_transformed():
    frame, consumed = build_canonical_brick_frame({"Satış Brick Yayılımı": pd.DataFrame([[1]])})
    assert frame is None
    assert consumed == set()


def test_product_kpi_name_detection_is_narrow():
    assert is_product_kpi_sheet("2-KUTU-TRAVAZOL KPI")
    assert not is_product_kpi_sheet("2-TTS-BRİCK KUTU-REA%")
    assert not is_product_kpi_sheet("Satış Brick Yayılımı")


def test_kpi_extra_columns_are_validation_only():
    canonical, _ = build_canonical_brick_frame({
        "2-TTS-BRİCK TL-REA%": _matrix("tl"),
        "2-TTS-BRİCK KUTU-REA%": _matrix("unit"),
    })
    kpi = pd.DataFrame([
        ["1-9 AĞUSTOS", None, None, None, None, None, None, None, None, None],
        [None, None, None, None, None, "TRAVAZOL", None, None, None, None],
        [None] * 10,
        [None, None, None, None, None, "PAZAR", "PP", "RANK", "TRAVAZOL KREM", "RAKIP"],
        ["BÖLGE", "İL", "NATIONAL", "NATIONAL", "", 100, None, None, 30, 70],
        ["101 ISTANBUL", "EDİRNE", "EDİRNE MERKEZ", "AYŞE TEST", "", 10, 30, 1, 3, 7],
    ])
    assert validate_product_kpi_sheets({"2-KUTU-TRAVAZOL KPI": kpi}, canonical) == 1


def test_kpi_validation_rejects_changed_core_value():
    canonical, _ = build_canonical_brick_frame({
        "2-TTS-BRİCK TL-REA%": _matrix("tl"),
        "2-TTS-BRİCK KUTU-REA%": _matrix("unit"),
    })
    kpi = pd.DataFrame([
        [None] * 9, [None] * 9, [None] * 9,
        [None, None, None, None, None, "PAZAR", "PP", "RANK", "TRAVAZOL"],
        ["BÖLGE", "İL", "NATIONAL", "NATIONAL", "", 100, None, None, 31],
        ["101 ISTANBUL", "EDİRNE", "EDİRNE MERKEZ", "AYŞE TEST", "", 10, 30, 1, 3],
    ])
    with pytest.raises(ValueError, match="KPI doğrulaması"):
        validate_product_kpi_sheets({"2-KUTU-TRAVAZOL KPI": kpi}, canonical)
