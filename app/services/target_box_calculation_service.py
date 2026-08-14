"""Persisted box-target calculation from the approved product price master."""

from app.extensions import db
from app.models import IMSSummary, Product, Target


class TargetBoxCalculationService:
    """Keeps the box equivalent of a TL target consistent across screens."""

    @staticmethod
    def unit_target(tl_target, unit_price):
        """Return a whole-box target, or zero when no usable price exists."""
        target = float(tl_target or 0)
        price = float(unit_price or 0)
        return float(round(target / price)) if target and price > 0 else 0.0

    @classmethod
    def synchronize(cls, year=None, month=None):
        """Recalculate stored box targets and matching summary values transaction-safely."""
        query = Target.query.join(Product, Product.id == Target.product_id)
        if year is not None:
            query = query.filter(Target.year == year)
        if month is not None:
            query = query.filter(Target.month == month)

        changed = 0
        for target in query.all():
            value = cls.unit_target(target.tl_target, target.product.unit_price)
            if target.unit_target != value:
                target.unit_target = value
                changed += 1
            summary = IMSSummary.query.filter_by(
                year=target.year, month=target.month,
                representative_id=target.representative_id, product_id=target.product_id,
            ).first()
            if summary is not None:
                summary.target_unit = value
        db.session.flush()
        return changed
