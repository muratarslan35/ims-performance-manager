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
        totals = defaultdict(lambda: {
            "target": 0.0, "target_actual": 0.0,
            "summary_actual": 0.0, "summary_count": 0,
        })
        if representative_ids:
            for month, target_value, actual_value in db.session.query(
                Target.month,
                func.coalesce(func.sum(Target.tl_target), 0.0),
                func.coalesce(func.sum(Target.tl_realization), 0.0),
            ).filter(
                Target.year == year,
                Target.representative_id.in_(representative_ids),
            ).group_by(Target.month).all():
                bucket = totals[int(month)]
                bucket["target"] = float(target_value or 0.0)
                bucket["target_actual"] = float(actual_value or 0.0)

            for month, value, count in db.session.query(
                IMSSummary.month,
                func.coalesce(func.sum(IMSSummary.tl), 0.0),
                func.count(IMSSummary.id),
            ).filter(
                IMSSummary.year == year,
                IMSSummary.representative_id.in_(representative_ids),
            ).group_by(IMSSummary.month).all():
                bucket = totals[int(month)]
                bucket["summary_actual"] = float(value or 0.0)
                bucket["summary_count"] = int(count or 0)

        rows = []
        for month, label in enumerate(cls.MONTHS, start=1):
            bucket = totals[month]
            # New imports persist verified IMS TL on Target. Older periods keep
            # their valid summary source; a genuine zero summary remains zero.
            actual = (
                bucket["target_actual"]
                if bucket["target_actual"] != 0
                else bucket["summary_actual"] if bucket["summary_count"] else 0.0
            )
            target = bucket["target"]
            rows.append({
                "month": month,
                "label": label,
                "target_tl": round(target, 2),
                "actual_tl": round(actual, 2),
                "percent": round(actual * 100.0 / target, 1) if target else None,
                "has_data": bool(target),
            })
        return rows
