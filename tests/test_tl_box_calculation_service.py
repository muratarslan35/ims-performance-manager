from decimal import Decimal

from app.services.tl_box_calculation_service import TLBoxCalculationService


def test_april_2026_start_gate():
    assert not TLBoxCalculationService.applies(2026, 3)
    assert TLBoxCalculationService.applies(2026, 4)
    assert TLBoxCalculationService.applies(2027, 1)


def test_approved_half_down_box_rounding():
    assert TLBoxCalculationService.round_box("3591.49") == Decimal("3591")
    assert TLBoxCalculationService.round_box("3591.50") == Decimal("3591")
    assert TLBoxCalculationService.round_box("3591.51") == Decimal("3592")


def test_diyarbakir_week16_exact_tl_box_examples():
    assert TLBoxCalculationService.boxes_from_tl("5133811.41", "128.31") == Decimal("40011")
    assert TLBoxCalculationService.boxes_from_tl("95169.40", "827.56") == Decimal("115")
    assert TLBoxCalculationService.boxes_from_tl("0", "179.10") == Decimal("0")
