"""Authoritative box-target synchronization.

Box targets are company-provided master facts. They must never be reconstructed
from TL target / unit price because that can change an exact target (for example
2590) into a calculated approximation (2591.81/2592).
"""
from app.extensions import db
from app.models import IMSSummary, Target


class TargetBoxCalculationService:
    """Propagate stored authoritative box targets without recalculation."""

    @staticmethod
    def unit_target(stored_unit_target, unit_price=None):
        # Compatibility signature: callers may still pass unit_price. It is
        # deliberately ignored. Never infer an official box target from TL.
        return stored_unit_target if stored_unit_target is not None else 0

    @classmethod
    def synchronize(cls, year=None, month=None):
        """Copy exact Target.unit_target values into summaries; never mutate Target."""
        query = Target.query
        if year is not None:
            query = query.filter(Target.year == year)
        if month is not None:
            query = query.filter(Target.month == month)

        changed = 0
        for target in query.all():
            value = target.unit_target if target.unit_target is not None else 0
            summary = IMSSummary.query.filter_by(
                year=target.year,
                month=target.month,
                representative_id=target.representative_id,
                product_id=target.product_id,
            ).first()
            if summary is not None and summary.target_unit != value:
                summary.target_unit = value
                changed += 1
        db.session.flush()
        return changed
