"""Late guard for legacy field-read adapters that still consult Product.unit_price."""
from decimal import Decimal

from app.services.product_unit_price_service import ProductUnitPriceService
from app.services.tl_box_calculation_service import TLBoxCalculationService


def install_period_price_read_guard():
    from app.services import week8_read_path_repair as week8

    if getattr(week8, "_period_price_guard_installed", False):
        return
    original = week8._apply_target_ims_actuals

    def period_aware(rows, targets, *, has_completed_ims, year=None, month=None):
        result = original(
            rows,
            targets,
            has_completed_ims=has_completed_ims,
            year=year,
            month=month,
        )
        if year is None or month is None or not TLBoxCalculationService.applies(year, month):
            return result
        targets_by_product = {int(item.product_id): item for item in targets}
        prices = ProductUnitPriceService.price_map(targets_by_product.keys(), year, month)
        for product_id, values in list((result or {}).items()):
            if values.get("source") != "IMS":
                continue
            target = targets_by_product.get(int(product_id))
            if target is None:
                continue
            # The Week-8 repair uses Target.tl_realization as the repaired IMS TL
            # source. Recompute only its box projection with the price frozen for
            # the requested month; all other source-selection rules stay intact.
            actual_tl = Decimal(str(values.get("actual_tl") or target.tl_realization or 0))
            price = prices.get(int(product_id))
            if Decimal(str(price or 0)) <= 0:
                continue
            repaired = dict(values)
            repaired["actual_unit"] = TLBoxCalculationService.boxes_from_tl(actual_tl, price)
            result[int(product_id)] = repaired
        return result

    week8._apply_target_ims_actuals = period_aware
    week8._period_price_guard_installed = True
