import pandas as pd
import pytest

from app.services.kpi_workbook_compat import (
    build_canonical_brick_frame,
    build_competition_frames,
    build_legacy_summary_frames,
    is_product_kpi_sheet,
    validate_product_kpi_sheets,
)


def _matrix(metric, rows=None, *, single_rep=False):
    phase = "TL" if metric == "tl" else "KUTU"
    frame = pd.DataFrame([
        ["1-9 AĞUSTOS", None, None, None, None, None, None, None, None, None, None],
        ["32.HAFTA", None, None, None, None, "TOPLAM", None, None, "TRAVAZOL", None, None],
        [None, None, None, "1.TTS", "2.TTS", "EKİP HEDEF", "EKİP ÇIKIŞ", "EKİP REAL", "ÜRÜN HEDEF", "ÜRÜN ÇIKIŞ", "REAL"],
        ["BÖLGE", "İL", "NATIONAL", "NATIONAL", "", 100, 40, 40, 80, 30, 37.5],
        ["101 ISTANBUL", "EDİRNE", "EDİRNE MERKEZ", "AYŞE TEST", "", 10, 4, 40, 8, rows if rows is not None else (300 if phase == "TL" else 3), 37.5],
    ])
    if single_rep:
        frame = frame.drop(columns=[4]).reset_index(drop=True)
    return frame


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


def test_numbered_sheet_group_with_one_rep_column_reads_all_bricks():
    workbook = {
        "2-TTS-BRİCK TL-REA%": _matrix("tl", single_rep=True),
        "2-TTS-BRİCK KUTU-REA%": _matrix("unit", single_rep=True),
    }
    frame, consumed = build_canonical_brick_frame(workbook)

    assert consumed == set(workbook)
    assert len(frame) == 2
    assert frame.iloc[1]["IAM BRICK"] == "EDİRNE MERKEZ"
    assert frame.iloc[1]["1 TTS ISMI"] == "AYŞE TEST"
    assert frame.iloc[1]["2 TTS ISMI"] == ""
    assert frame.iloc[1]["TRAVAZOL KUTU ÇIKIŞ"] == 3
    assert frame.iloc[1]["TRAVAZOL TL ÇIKIŞ"] == 300


def test_semantic_tts_brick_headers_are_supported_without_changing_identity_mapping():
    tl = _matrix("tl", single_rep=True)
    unit = _matrix("unit", single_rep=True)
    for frame in (tl, unit):
        frame.iloc[2, 2] = "TTS / BRICK"
        frame.iloc[2, 3] = "TTS"

    workbook = {
        "2-TTS-BRİCK HEDEF REAL-TL V2": tl,
        "2-TTS-BRİCK HEDEF REAL-KUTU V2": unit,
    }
    frame, consumed = build_canonical_brick_frame(workbook)

    assert consumed == set(workbook)
    assert len(frame) == 2
    assert frame.iloc[1]["BÖLGE"] == "101 ISTANBUL"
    assert frame.iloc[1]["İL"] == "EDİRNE"
    assert frame.iloc[1]["IAM BRICK"] == "EDİRNE MERKEZ"
    assert frame.iloc[1]["1 TTS ISMI"] == "AYŞE TEST"
    assert frame.iloc[1]["2 TTS ISMI"] == ""
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


def test_new_layout_builds_legacy_dashboard_target_and_actual_views():
    workbook = {
        "2-TTS-BRİCK TL-REA%": _matrix("tl"),
        "2-TTS-BRİCK KUTU-REA%": _matrix("unit"),
    }
    frames = build_legacy_summary_frames(workbook)

    balance = frames["IMS COMPAT BAKIYE"]
    weekly = frames["IMS COMPAT HAFTALIK CIKIS"]
    assert "HEDEF" in str(balance.iloc[1, 1])
    assert balance.iloc[2, 1] == "NATIONAL"
    assert balance.iloc[3, 1] == "AYŞE TEST"
    assert balance.iloc[3, 2] == 8
    assert balance.iloc[3, -1] == 8
    assert weekly.iloc[2, 1] == "NATIONAL"
    assert weekly.iloc[3, 2] == 300
    assert weekly.iloc[3, 3] == 3


def test_kpi_market_and_named_rivals_are_translated_but_pp_rank_are_not():
    kpi = pd.DataFrame([
        ["1-9 AĞUSTOS", None, None, None, None, None, None, None, None, None],
        [None, None, None, None, None, "TRAVAZOL", None, None, None, None],
        [None] * 10,
        [None, None, None, None, None, "PAZAR", "PP", "RANK", "TRAVAZOL KREM", "RAKIP"],
        ["BÖLGE", "İL", "NATIONAL", "NATIONAL", "", 100, None, None, 30, 70],
        ["101 ISTANBUL", "EDİRNE", "EDİRNE MERKEZ", "AYŞE TEST", "", 10, 30, 1, 3, 7],
    ])
    frames = build_competition_frames({"2-KUTU-TRAVAZOL KPI": kpi})
    frame = next(iter(frames.values()))

    assert frame.iloc[2].tolist()[-3:] == ["TRAVAZOL SUBTOTAL", "TRAVAZOL KREM", "RAKIP"]
    assert frame.iloc[4].tolist()[-3:] == [10, 3, 7]
    assert "PP" not in frame.iloc[2].tolist()
    assert "RANK" not in frame.iloc[2].tolist()


def test_kpi_validation_keeps_market_tab_independent_from_company_sales_matrix():
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
    assert validate_product_kpi_sheets({"2-KUTU-TRAVAZOL KPI": kpi}, canonical) == 1


def test_kpi_validation_skips_semantically_repeated_identity_labels_before_national_control():
    canonical, _ = build_canonical_brick_frame({
        "2-TTS-BRİCK TL-REA%": _matrix("tl"),
        "2-TTS-BRİCK KUTU-REA%": _matrix("unit"),
    })
    # The source KPI repeats field labels in a NATIONAL-shaped row. The
    # placeholder identity is absent from the canonical matrix, while the
    # separate real NATIONAL control must still pass canonical validation.
    canonical = canonical[canonical["IAM BRICK"] != "NATIONAL"].copy()
    canonical.loc[len(canonical)] = ["", "", "NATIONAL", "NATIONAL", "", 0, 0]
    kpi = pd.DataFrame([
        [None] * 9, [None] * 9, [None] * 9,
        [None, None, None, None, None, "PAZAR", "PP", "RANK", "TRAVAZOL"],
        ["BÖLGE", "İL", "NATIONAL", "NATIONAL", "", 100, None, None, 31],
        ["101 ISTANBUL", "EDİRNE", "EDİRNE MERKEZ", "AYŞE TEST", "", 10, 30, 1, 3],
        ["", "", "NATIONAL", "NATIONAL", "", 100, None, None, 31],
    ])
    assert validate_product_kpi_sheets({"2-KUTU-TRAVAZOL KPI": kpi}, canonical) == 1


def test_kpi_validation_accepts_numeric_repeated_identity_national_control_without_canonical_match():
    canonical, _ = build_canonical_brick_frame({
        "2-TTS-BRİCK TL-REA%": _matrix("tl"),
        "2-TTS-BRİCK KUTU-REA%": _matrix("unit"),
    })
    # This export repeats the identity labels in its only NATIONAL-shaped
    # KPI row. The measure cells are numeric, so it is the source control row
    # even though its identity tuple is not a canonical brick key.
    canonical = canonical[canonical["IAM BRICK"] != "NATIONAL"].copy()
    kpi = pd.DataFrame([
        [None] * 9, [None] * 9, [None] * 9,
        [None, None, None, None, None, "PAZAR", "PP", "RANK", "TRAVAZOL"],
        ["BÖLGE", "İL", "NATIONAL", "NATIONAL", "", 100, None, None, 31],
        ["101 ISTANBUL", "EDİRNE", "EDİRNE MERKEZ", "AYŞE TEST", "", 10, 30, 1, 3],
    ])
    assert validate_product_kpi_sheets({"2-KUTU-TRAVAZOL KPI": kpi}, canonical) == 1


def test_kpi_validation_rejects_non_numeric_national_market_value():
    canonical, _ = build_canonical_brick_frame({
        "2-TTS-BRİCK TL-REA%": _matrix("tl"),
        "2-TTS-BRİCK KUTU-REA%": _matrix("unit"),
    })
    kpi = pd.DataFrame([
        [None] * 9, [None] * 9, [None] * 9,
        [None, None, None, None, None, "PAZAR", "PP", "RANK", "TRAVAZOL"],
        ["BÖLGE", "İL", "NATIONAL", "NATIONAL", "", "eksik", None, None, 31],
    ])
    with pytest.raises(ValueError, match="sayısal değil"):
        validate_product_kpi_sheets({"2-KUTU-TRAVAZOL KPI": kpi}, canonical)


def test_kpi_validation_accepts_negative_return_correction():
    canonical, _ = build_canonical_brick_frame({
        "2-TTS-BRİCK TL-REA%": _matrix("tl"),
        "2-TTS-BRİCK KUTU-REA%": _matrix("unit"),
    })
    kpi = pd.DataFrame([
        [None] * 9, [None] * 9, [None] * 9,
        [None, None, None, None, None, "PAZAR", "PP", "RANK", "TRAVAZOL"],
        ["BÖLGE", "İL", "NATIONAL", "NATIONAL", "", 100, None, None, -1],
    ])
    assert validate_product_kpi_sheets({"2-KUTU-TRAVAZOL KPI": kpi}, canonical) == 1


def _v2_matrix(metric, *, mismatch_summary=False):
    summary_target = 101 if mismatch_summary else 100
    return pd.DataFrame([
        ["1-11 EKİM", None, None, None, None, None, None, None, None, None, None],
        [None, None, None, None, None, "TOPLAM", None, None, "TRAVAZOL", None, None],
        ["BÖLGE", "İL", "TTS / BRICK", "TTS", "EKİP HEDEF", "EKİP ÇIKIŞ", "EKİP REAL", None, "ÜRÜN HEDEF", "ÜRÜN ÇIKIŞ", "REAL"],
        ["TÜRKİYE TOPLAM", None, None, None, 100, 40, 40, None, 100, 40, 40],
        ["101 ISTANBUL", "", "101 ISTANBUL", "", 100, 40, 40, None, 100, 40, 40],
        ["101 ISTANBUL", "", "AYŞE TEST", "AYŞE TEST", summary_target, 40, 40, None, summary_target, 40, 40],
        ["101 ISTANBUL", "EDİRNE", "EDİRNE MERKEZ", "AYŞE TEST", 60, 20, 33.3, None, 60, 20, 33.3],
        ["101 ISTANBUL", "TEKİRDAĞ", "TEKİRDAĞ MERKEZ", "AYŞE TEST", 40, 20, 50, None, 40, 20, 50],
    ])


def test_v2_canonical_sales_excludes_national_region_and_tts_summary_rows():
    workbook = {
        "2-TTS-BRİCK HEDEF REAL-TL V2": _v2_matrix("tl"),
        "2-TTS-BRİCK HEDEF REAL-KUTU V2": _v2_matrix("unit"),
    }
    canonical, consumed = build_canonical_brick_frame(workbook)

    assert consumed == set(workbook)
    assert len(canonical) == 2
    assert set(canonical["IAM BRICK"]) == {"EDİRNE MERKEZ", "TEKİRDAĞ MERKEZ"}
    assert set(canonical["1 TTS ISMI"]) == {"AYŞE TEST"}


def test_v2_compat_summary_preserves_official_totals_without_double_counting():
    workbook = {
        "2-TTS-BRİCK HEDEF REAL-TL V2": _v2_matrix("tl"),
        "2-TTS-BRİCK HEDEF REAL-KUTU V2": _v2_matrix("unit"),
    }
    frames = build_legacy_summary_frames(workbook)
    balance = frames["IMS COMPAT BAKIYE"]
    weekly = frames["IMS COMPAT HAFTALIK CIKIS"]

    # National, region, and representative are distinct summary identities.
    assert balance.iloc[2, 1] == "NATIONAL"
    assert balance.iloc[3, 0] == "101 ISTANBUL"
    assert balance.iloc[4, 1] == "AYŞE TEST"
    assert balance.iloc[4, 2] == 100
    assert weekly.iloc[4, 2] == 40
    assert weekly.iloc[4, 3] == 40


def test_v2_compat_summary_fails_closed_when_tts_summary_does_not_match_details():
    workbook = {
        "2-TTS-BRİCK HEDEF REAL-TL V2": _v2_matrix("tl", mismatch_summary=True),
        "2-TTS-BRİCK HEDEF REAL-KUTU V2": _v2_matrix("unit"),
    }
    with pytest.raises(ValueError, match="TTS özeti brick detaylarıyla uyuşmuyor"):
        build_legacy_summary_frames(workbook)


def test_v2_compat_summary_fails_closed_when_national_does_not_match_region_totals():
    tl = _v2_matrix("tl")
    unit = _v2_matrix("unit")
    tl.iloc[4, 8] = 99
    with pytest.raises(ValueError, match="Türkiye toplamı bölge toplamlarıyla uyuşmuyor"):
        build_legacy_summary_frames({
            "2-TTS-BRİCK HEDEF REAL-TL V2": tl,
            "2-TTS-BRİCK HEDEF REAL-KUTU V2": unit,
        })
