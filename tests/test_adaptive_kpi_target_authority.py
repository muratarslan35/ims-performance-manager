import pandas as pd

from app.services.adaptive_kpi_target_authority import _find_pair, _matrix_plan, _source_rows


def _matrix(metric, *, single_rep=False):
    actual = 300.0 if metric == "tl" else 3.0
    target = 800.0 if metric == "tl" else 8.0
    frame = pd.DataFrame([
        ["1-9 AĞUSTOS", None, None, None, None, None, None, None],
        ["32.HAFTA", None, None, None, None, "TRAVAZOL", None, None],
        [None, None, None, "1.TTS", "2.TTS", "ÜRÜN HEDEF", "ÜRÜN ÇIKIŞ", "REAL"],
        ["BÖLGE", "İL", "NATIONAL", "NATIONAL", "", target, actual, 37.5],
        ["101 ISTANBUL", "EDİRNE", "EDİRNE MERKEZ", "AYŞE TEST", "", target / 2, actual / 2, 37.5],
        ["101 ISTANBUL", "101 ISTANBUL Subtotal", "101 ISTANBUL", "101 ISTANBUL", "", target, actual, 37.5],
    ])
    if single_rep:
        frame = frame.drop(columns=[4]).reset_index(drop=True)
    return frame


def test_pair_accepts_one_representative_identity_column():
    pair = _find_pair({
        "2-TTS-BRİCK TL-REA%": _matrix("tl", single_rep=True),
        "2-TTS-BRİCK KUTU-REA%": _matrix("unit", single_rep=True),
    })
    assert pair is not None
    assert pair[0][2]["secondary_rep"] is None
    assert pair[1][2]["secondary_rep"] is None


def test_pair_detection_uses_structure_not_exact_sheet_name():
    workbook = {
        "Yeni Rapor TL Sonuçları": _matrix("tl"),
        "Yeni Rapor KUTU Sonuçları": _matrix("unit"),
    }
    pair = _find_pair(workbook)
    assert pair[0][0] == "Yeni Rapor TL Sonuçları"
    assert pair[1][0] == "Yeni Rapor KUTU Sonuçları"


def test_region_subtotal_is_detected_from_identity_not_subtotal_cell_position():
    frame = _matrix("tl")
    plan = _matrix_plan(frame)
    products, aggregates, reps = _source_rows(frame, plan)
    assert products == ["TRAVAZOL"]
    identities = {(territory, representative) for territory, representative, _ in aggregates}
    assert ("NATIONAL", "NATIONAL") in identities
    assert ("101", "101 ISTANBUL") in identities
    assert ("101 ISTANBUL", "AYŞE TEST") in reps


def test_pair_detection_does_not_guess_metric_without_semantic_hint():
    assert _find_pair({
        "Rapor A": _matrix("tl"),
        "Rapor B": _matrix("unit"),
    }) is None

def test_pair_accepts_semantic_tts_brick_header_for_week_41():
    tl = _matrix("tl", single_rep=True)
    unit = _matrix("unit", single_rep=True)
    for frame in (tl, unit):
        frame.iloc[2, 2] = "TTS / BRICK"
        frame.iloc[2, 3] = "TTS"

    pair = _find_pair({
        "2-TTS-BRİCK TL-REA%": tl,
        "2-TTS-BRİCK KUTU-REA%": unit,
    })

    assert pair is not None
    assert pair[0][2]["brick"] == 2
    assert pair[0][2]["primary_rep"] == 3
    assert pair[0][2]["secondary_rep"] is None
    assert pair[1][2]["secondary_rep"] is None



def _v2_matrix(metric, *, mismatch_summary=False):
    national_target, national_actual = 100.0, 40.0
    summary_target = 101.0 if mismatch_summary else 100.0
    return pd.DataFrame([
        ["1-11 EKİM", None, None, None, None, None, None, None],
        [None, None, None, None, None, "TRAVAZOL", None, None],
        ["BÖLGE", "İL", "TTS / BRICK", "TTS", None, "ÜRÜN HEDEF", "ÜRÜN ÇIKIŞ", "REAL"],
        ["TÜRKİYE TOPLAM", None, None, None, None, national_target, national_actual, 40.0],
        ["101 ISTANBUL", "", "101 ISTANBUL", "", None, national_target, national_actual, 40.0],
        ["101 ISTANBUL", "", "AYŞE TEST", "AYŞE TEST", None, summary_target, 40.0, 40.0],
        ["101 ISTANBUL", "EDİRNE", "EDİRNE MERKEZ", "AYŞE TEST", None, 60.0, 20.0, 33.3],
        ["101 ISTANBUL", "TEKİRDAĞ", "TEKİRDAĞ MERKEZ", "AYŞE TEST", None, 40.0, 20.0, 50.0],
    ])


def test_v2_turkiye_region_and_tts_summary_rows_are_semantic_and_not_double_counted():
    tl = _v2_matrix("tl")
    unit = _v2_matrix("unit")
    pair = _find_pair({
        "2-TTS-BRİCK HEDEF REAL-TL V2": tl,
        "2-TTS-BRİCK HEDEF REAL-KUTU V2": unit,
    })
    assert pair is not None
    plan = pair[0][2]
    products, aggregates, reps = _source_rows(tl, plan)

    assert products == ["TRAVAZOL"]
    aggregate_map = {(territory, representative): values for territory, representative, values in aggregates}
    assert aggregate_map[("NATIONAL", "NATIONAL")]["TRAVAZOL"] == {"target": 100.0, "actual": 40.0}
    assert aggregate_map[("101", "101 ISTANBUL")]["TRAVAZOL"] == {"target": 100.0, "actual": 40.0}
    assert reps[("101 ISTANBUL", "AYŞE TEST")]["TRAVAZOL"] == {"target": 100.0, "actual": 40.0}


def test_v2_tts_summary_mismatch_fails_closed():
    frame = _v2_matrix("tl", mismatch_summary=True)
    plan = _matrix_plan(frame)
    try:
        _source_rows(frame, plan)
    except ValueError as exc:
        assert "TTS özeti brick detaylarıyla uyuşmuyor" in str(exc)
    else:
        raise AssertionError("V2 summary mismatch must fail closed")
