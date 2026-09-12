import pandas as pd

from app.services.adaptive_kpi_target_authority import _find_pair, _matrix_plan, _source_rows


def _matrix(metric):
    actual = 300.0 if metric == "tl" else 3.0
    target = 800.0 if metric == "tl" else 8.0
    return pd.DataFrame([
        ["1-9 AĞUSTOS", None, None, None, None, None, None, None],
        ["32.HAFTA", None, None, None, None, "TRAVAZOL", None, None],
        [None, None, None, "1.TTS", "2.TTS", "ÜRÜN HEDEF", "ÜRÜN ÇIKIŞ", "REAL"],
        ["BÖLGE", "İL", "NATIONAL", "NATIONAL", "", target, actual, 37.5],
        ["101 ISTANBUL", "EDİRNE", "EDİRNE MERKEZ", "AYŞE TEST", "", target / 2, actual / 2, 37.5],
        ["101 ISTANBUL", "101 ISTANBUL Subtotal", "101 ISTANBUL", "101 ISTANBUL", "", target, actual, 37.5],
    ])


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
