"""Batch the representative monthly/quarterly/half-year read model.

The old implementation evaluated overlapping 1/3/6-month windows independently
and called ``ProductionResultService.effective_product`` once per target row in
each window.  That preserved business rules but generated a large N+1 query fan
out on every representative page.

This service loads the six-month target, IMS summary and applied production result
sources once, then applies the exact P2 > P1 > IMS precedence in memory.  It is
read-only and does not alter target/production/IMS data.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import and_, or_

from app.extensions import db
from app.models import (
    IMSSummary,
    Product,
    ProductionResult,
    ProductionResultUpload,
    Target,
)


class RepresentativePeriodSnapshotService:
    PERIODS = (("monthly", "Aylık", 1), ("quarterly", "3 Aylık", 3), ("half_year", "6 Aylık", 6))

    @staticmethod
    def _shift_month(year, month, delta):
        ordinal = int(year) * 12 + int(month) - 1 + int(delta)
        return ordinal // 12, ordinal % 12 + 1

    @classmethod
    def _months(cls, year, month, length):
        return [cls._shift_month(year, month, delta) for delta in range(-(length - 1), 1)]

    @staticmethod
    def _percent(actual, target):
        return round(float(actual or 0) * 100 / float(target), 1) if target else 0.0

    @staticmethod
    def _period_filter(model, periods):
        return or_(*[
            and_(model.year == year, model.month == month)
            for year, month in sorted(periods)
        ])

    @classmethod
    def build(cls, representative_id, year, month):
        representative_id = int(representative_id)
        year, month = int(year), int(month)
        all_months = cls._months(year, month, 6)
        allowed = set(all_months)

        # One target read for all overlapping windows.
        targets = Target.query.filter(
            Target.representative_id == representative_id,
            cls._period_filter(Target, allowed),
        ).all()
        if not targets:
            return {
                key: {
                    "key": key,
                    "label": label,
                    "month_count": length,
                    "target_tl": Decimal("0"),
                    "actual_tl": None,
                    "realization_percent": None,
                    "gap_tl": None,
                    "complete": False,
                    "products": [],
                    "representatives": [],
                }
                for key, label, length in cls.PERIODS
            }

        product_ids = {int(target.product_id) for target in targets}

        # One IMS read for the same six-month grain.
        summaries = IMSSummary.query.filter(
            IMSSummary.representative_id == representative_id,
            IMSSummary.product_id.in_(product_ids),
            cls._period_filter(IMSSummary, allowed),
        ).all()
        summary_by_key = {
            (int(item.year), int(item.month), int(item.product_id)): item
            for item in summaries
        }

        # One applied-production upload read for all six months.  Ordering is
        # identical to ProductionResultService.applied_uploads(), so choosing
        # the first row with a product result preserves P2 > P1 > IMS exactly.
        uploads = ProductionResultUpload.query.filter(
            ProductionResultUpload.status == ProductionResultUpload.STATUS_APPLIED,
            cls._period_filter(ProductionResultUpload, allowed),
        ).order_by(
            ProductionResultUpload.year.asc(),
            ProductionResultUpload.month.asc(),
            ProductionResultUpload.production_stage.desc(),
            ProductionResultUpload.applied_at.desc(),
            ProductionResultUpload.id.desc(),
        ).all()
        uploads_by_period = defaultdict(list)
        for upload in uploads:
            uploads_by_period[(int(upload.year), int(upload.month))].append(upload)

        upload_ids = [int(upload.id) for upload in uploads]
        production_results = []
        if upload_ids:
            production_results = ProductionResult.query.filter(
                ProductionResult.upload_id.in_(upload_ids),
                ProductionResult.representative_id == representative_id,
                ProductionResult.product_id.in_(product_ids),
            ).all()
        production_by_key = {
            (int(item.upload_id), int(item.product_id)): item
            for item in production_results
        }

        products = Product.query.filter(Product.id.in_(product_ids)).all()
        product_by_id = {int(product.id): product for product in products}

        # Resolve every six-month target once according to the canonical source
        # priority.  The same resolved rows are reused by 1/3/6-month windows.
        resolved = {}
        for target in targets:
            period = (int(target.year), int(target.month))
            product_id = int(target.product_id)
            target_tl = Decimal(str(target.tl_target or 0))
            selected_result = None
            for upload in uploads_by_period.get(period, ()):  # P2, then P1, then IMS
                selected_result = production_by_key.get((int(upload.id), product_id))
                if selected_result is not None:
                    break

            if selected_result is not None:
                percent = Decimal(str(selected_result.realization_percent or 0))
                actual_tl = target_tl * percent / Decimal("100")
                complete = True
            else:
                summary = summary_by_key.get((period[0], period[1], product_id))
                actual_tl = Decimal(str(summary.tl if summary else 0))
                complete = summary is not None

            resolved[(period[0], period[1], product_id)] = {
                "product_id": product_id,
                "target_tl": target_tl,
                "actual_tl": actual_tl,
                "complete": complete,
            }

        result = {}
        for key, label, length in cls.PERIODS:
            months = cls._months(year, month, length)
            month_set = set(months)
            product_totals = defaultdict(
                lambda: {"target": Decimal("0"), "actual": Decimal("0"), "complete": True}
            )
            month_totals = defaultdict(
                lambda: {"target": Decimal("0"), "actual": Decimal("0"), "complete": True}
            )

            for (row_year, row_month, product_id), row in resolved.items():
                period = (row_year, row_month)
                if period not in month_set:
                    continue
                for bucket in (product_totals[product_id], month_totals[period]):
                    bucket["target"] += row["target_tl"]
                    bucket["actual"] += row["actual_tl"]
                    bucket["complete"] = bucket["complete"] and row["complete"]

            product_rows = []
            for product_id, values in product_totals.items():
                complete = bool(values["complete"])
                product = product_by_id.get(product_id)
                product_rows.append({
                    "product_id": product_id,
                    "product_name": product.product_name if product else f"Ürün {product_id}",
                    "target_tl": values["target"],
                    "actual_tl": values["actual"] if complete else None,
                    "realization_percent": (
                        cls._percent(values["actual"], values["target"]) if complete else None
                    ),
                    "gap_tl": (
                        max(values["target"] - values["actual"], Decimal("0")) if complete else None
                    ),
                    "complete": complete,
                })

            total_target = sum((values["target"] for values in month_totals.values()), Decimal("0"))
            total_actual = sum((values["actual"] for values in month_totals.values()), Decimal("0"))
            complete = bool(month_totals) and all(values["complete"] for values in month_totals.values())
            result[key] = {
                "key": key,
                "label": label,
                "month_count": len(months),
                "target_tl": total_target,
                "actual_tl": total_actual if complete else None,
                "realization_percent": cls._percent(total_actual, total_target) if complete else None,
                "gap_tl": max(total_target - total_actual, Decimal("0")) if complete else None,
                "complete": complete,
                "products": product_rows,
                "representatives": [],
            }
        return result
