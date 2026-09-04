"""Read-only 12-month TL realization series for representative and region charts."""

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.models import IMSSummary, ProductionResult, ProductionResultUpload, Target


class AnnualRealizationService:
    MONTHS = (
        "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
        "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
    )

    @classmethod
    def build(cls, year, representative_ids):
        """Legacy aggregate read path retained for region consumers."""
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

    @classmethod
    def build_representative(cls, year, representative_id):
        """Build one representative's chart from the strongest source per product/month.

        Source authority is product scoped and automatic:
        P2 > P1 > IMS summary > persisted TL fallback.
        Therefore completed historical months follow accepted production files,
        while the open month follows the latest IMS until an accepted production
        result arrives. If IMS is not available yet, Target.tl_realization is the
        read-only TL fallback and the chart percentage remains actual TL / target TL.
        """
        year = int(year)
        representative_id = int(representative_id)

        targets = Target.query.filter_by(
            year=year, representative_id=representative_id
        ).all()
        if not targets:
            return [
                {
                    "month": month,
                    "label": label,
                    "target_tl": 0.0,
                    "actual_tl": 0.0,
                    "percent": None,
                    "has_data": False,
                    "source": None,
                }
                for month, label in enumerate(cls.MONTHS, start=1)
            ]

        product_ids = sorted({int(target.product_id) for target in targets})
        summaries = IMSSummary.query.filter(
            IMSSummary.year == year,
            IMSSummary.representative_id == representative_id,
            IMSSummary.product_id.in_(product_ids),
        ).all()
        summary_by_key = {
            (int(item.month), int(item.product_id)): item for item in summaries
        }

        uploads = ProductionResultUpload.query.filter(
            ProductionResultUpload.year == year,
            ProductionResultUpload.status == ProductionResultUpload.STATUS_APPLIED,
        ).order_by(
            ProductionResultUpload.month.asc(),
            ProductionResultUpload.production_stage.desc(),
            ProductionResultUpload.applied_at.desc(),
            ProductionResultUpload.id.desc(),
        ).all()
        uploads_by_month = defaultdict(list)
        for upload in uploads:
            uploads_by_month[int(upload.month)].append(upload)

        upload_ids = [int(upload.id) for upload in uploads]
        production_rows = []
        if upload_ids:
            production_rows = ProductionResult.query.filter(
                ProductionResult.upload_id.in_(upload_ids),
                ProductionResult.representative_id == representative_id,
                ProductionResult.product_id.in_(product_ids),
            ).all()
        production_by_key = {
            (int(item.upload_id), int(item.product_id)): item
            for item in production_rows
        }

        month_totals = defaultdict(lambda: {
            "target": Decimal("0"),
            "actual": Decimal("0"),
            "sources": set(),
        })
        for target in targets:
            month = int(target.month)
            product_id = int(target.product_id)
            target_tl = Decimal(str(target.tl_target or 0))
            bucket = month_totals[month]
            bucket["target"] += target_tl

            selected_result = None
            selected_upload = None
            for upload in uploads_by_month.get(month, ()):
                result = production_by_key.get((int(upload.id), product_id))
                if result is not None:
                    selected_result = result
                    selected_upload = upload
                    break

            if selected_result is not None:
                percent = Decimal(str(selected_result.realization_percent or 0))
                actual_tl = target_tl * percent / Decimal("100")
                source = f"PRODUCTION_{int(selected_upload.production_stage)}"
            else:
                summary = summary_by_key.get((month, product_id))
                if summary is not None:
                    actual_tl = Decimal(str(summary.tl or 0))
                    source = "IMS"
                else:
                    actual_tl = Decimal(str(target.tl_realization or 0))
                    source = "TL_FALLBACK"

            bucket["actual"] += actual_tl
            bucket["sources"].add(source)

        rows = []
        for month, label in enumerate(cls.MONTHS, start=1):
            bucket = month_totals[month]
            target = float(bucket["target"])
            actual = float(bucket["actual"])
            sources = bucket["sources"]
            if not sources:
                source = None
            elif len(sources) == 1:
                source = next(iter(sources))
            else:
                source = "MIXED"
            rows.append({
                "month": month,
                "label": label,
                "target_tl": round(target, 2),
                "actual_tl": round(actual, 2),
                "percent": round(actual * 100.0 / target, 1) if target else None,
                "has_data": bool(target),
                "source": source,
            })
        return rows
