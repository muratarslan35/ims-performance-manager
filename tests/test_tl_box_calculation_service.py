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


def test_diyarbakir_week16_seven_product_tl_box_snapshot():
    rows = (
        # product, unit price, TL target, TL actual, target boxes, actual boxes
        ("TRAVAZOL", "128.31", "7624463", "5133811", "59422", "40011"),
        ("MONUROL", "100.37", "2231225", "1035517", "22230", "10317"),
        ("ACNEMIX", "230.57", "1244832", "822674", "5399", "3568"),
        ("MIXOVUL", "160.89", "513230", "311161", "3190", "1934"),
        ("STIDERM", "100.37", "347219", "235669", "3459", "2348"),
        ("BRIMODER", "827.56", "136547", "95169", "165", "115"),
        ("FENTIVAG", "179.10", "0", "0", "0", "0"),
    )
    for product, price, target_tl, actual_tl, target_box, actual_box in rows:
        assert TLBoxCalculationService.boxes_from_tl(target_tl, price) == Decimal(target_box), product
        assert TLBoxCalculationService.boxes_from_tl(actual_tl, price) == Decimal(actual_box), product
        assert (
            TLBoxCalculationService.boxes_from_tl(target_tl, price)
            - TLBoxCalculationService.boxes_from_tl(actual_tl, price)
        ) == Decimal(str(int(target_box) - int(actual_box))), product
