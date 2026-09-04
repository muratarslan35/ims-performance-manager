"""April 2026+ IMS TL-to-box conversion with the approved display rounding."""
from decimal import Decimal, ROUND_HALF_DOWN


class TLBoxCalculationService:
    START_PERIOD = (2026, 4)

    @classmethod
    def applies(cls, year, month):
        return (int(year), int(month)) >= cls.START_PERIOD

    @staticmethod
    def round_box(value):
        """Nearest integer; exact .50 stays down, values above .50 go up."""
        return Decimal(str(value or 0)).quantize(Decimal("1"), rounding=ROUND_HALF_DOWN)

    @classmethod
    def boxes_from_tl(cls, tl_value, unit_price):
        price = Decimal(str(unit_price or 0))
        if price <= 0:
            return Decimal("0")
        return cls.round_box(Decimal(str(tl_value or 0)) / price)
