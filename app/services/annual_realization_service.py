"""Read-only 12-month TL realization series for representative and region charts."""

from collections import defaultdict

from sqlalchemy import func

from app.extensions import db
from app.models import IMSSummary, Target


class AnnualRealizationService:
    MONTHS = (
        "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
        "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
    )

    @classmethod
    def build(cls, year, representative_ids):
        year = int(year)
        representative_ids = [int(item) for item in representative_ids]
        totals = defaultdict(lambda: {"target": 0.0, "actual": 0.0})
        if representative_ids:
            for month, value in db.session.query(
                Target.month, func.coalesce(func.sum(Target.tl_target), 0.0)
            ).filter(
                Target.year == year,
                Target.representative_id.in_(representative_ids),
            ).group_by(Target.month).all():
                totals[int(month)]["target"] = float(value or 0.0)

            for month, value in db.session.query(
                IMSSummary.month, func.coalesce(func.sum(IMSSummary.tl), 0.0)
            ).filter(
                IMSSummary.year == year,
                IMSSummary.representative_id.in_(representative_ids),
            ).group_by(IMSSummary.month).all():
                totals[int(month)]["actual"] = float(value or 0.0)

        return [
            {
                "month": month,
                "label": label,
                "target_tl": round(totals[month]["target"], 2),
                "actual_tl": round(totals[month]["actual"], 2),
                "percent": (
                    round(totals[month]["actual"] * 100.0 / totals[month]["target"], 1)
                    if totals[month]["target"] else None
                ),
                "has_data": bool(totals[month]["target"]),
            }
            for month, label in enumerate(cls.MONTHS, start=1)
        ]
