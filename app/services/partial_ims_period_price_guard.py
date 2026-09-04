"""Keep TL-only partial weekly IMS derivation on the active month's frozen price."""

from app.extensions import db
from app.models import IMSSummary, Product, Target
from app.services.product_unit_price_service import ProductUnitPriceService


def install_partial_ims_period_price_guard():
    from app.services import partial_ims_import_carry_forward as carry

    if getattr(carry, "_period_price_guard_installed", False):
        return

    def period_aware_apply_overlay_actuals(upload_id: int, year: int, month: int, baseline: dict):
        summaries = IMSSummary.query.filter_by(
            upload_id=int(upload_id), year=int(year), month=int(month)
        ).all()
        targets = {
            (int(row.representative_id), int(row.product_id)): row
            for row in Target.query.filter_by(year=int(year), month=int(month)).all()
        }
        product_ids = {int(row.product_id) for row in summaries if row.product_id is not None}
        period_prices = ProductUnitPriceService.price_map(product_ids, year, month)
        # Keep the product lookup only for compatibility with rows that may have
        # no managed price/history. It must never override a valid period price.
        products = {
            int(row.id): row
            for row in Product.query.filter(Product.id.in_(product_ids)).all()
        } if product_ids else {}

        changed = 0
        unit_sources = {}
        for summary in summaries:
            if summary.representative_id is None or summary.product_id is None:
                continue
            key = (int(summary.representative_id), int(summary.product_id))
            previous_unit, previous_tl = baseline.get(key, (0.0, 0.0))
            target = targets.get(key)
            product = products.get(int(summary.product_id))
            current_tl = float(summary.tl or 0.0)
            current_unit = float(summary.unit or 0.0)
            configured_price = period_prices.get(int(summary.product_id))
            if not configured_price and product is not None:
                configured_price = float(product.unit_price or 0.0)

            derived_unit, unit_source = carry.derive_missing_unit_delta(
                month=month,
                incremental_tl=current_tl,
                incremental_unit=current_unit,
                previous_unit=previous_unit,
                previous_tl=previous_tl,
                target_unit=float(target.unit_target or 0.0) if target is not None else 0.0,
                target_tl=float(target.tl_target or 0.0) if target is not None else 0.0,
                configured_unit_price=float(configured_price or 0.0),
            )
            unit_sources[unit_source] = unit_sources.get(unit_source, 0) + 1
            overlay_unit, overlay_tl = carry.overlay_snapshot_actuals(
                previous_unit, previous_tl, derived_unit, current_tl
            )

            if target is not None:
                target.unit_realization = overlay_unit
                target.tl_realization = overlay_tl
                target_tl = float(target.tl_target or 0.0)
                target.realization_percent = round(overlay_tl * 100.0 / target_tl, 2) if target_tl else 0.0
                summary.target_unit = float(target.unit_target or 0.0)
                summary.target_tl = target_tl
            else:
                target_tl = float(summary.target_tl or 0.0)

            summary.unit = overlay_unit
            summary.tl = overlay_tl
            summary.realization_percent = round(overlay_tl * 100.0 / target_tl, 2) if target_tl else 0.0
            changed += 1

        if changed:
            db.session.flush()
        return changed, unit_sources

    carry._apply_overlay_actuals = period_aware_apply_overlay_actuals
    carry._period_price_guard_installed = True
