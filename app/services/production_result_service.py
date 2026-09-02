from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal

from app.models import (
    IMSSummary,
    ProductionRegionProductResult,
    ProductionResult,
    ProductionResultUpload,
    Target,
)


class ProductionResultService:
    """Single source of truth for accepted period realizations.

    Priority is evaluated per representative/product with no waiting state:
    production 2 > production 1 > IMS. Production percentages are final, may
    exceed 100, and exact stored TL/unit targets are never rounded or rebuilt.
    """

    _effective_batch_override = ContextVar("production_effective_batch_override", default=None)

    @staticmethod
    def _d(value):
        return Decimal(str(value or 0))

    @classmethod
    def applied_uploads(cls, year, month):
        return (
            ProductionResultUpload.query.filter_by(
                year=year, month=month, status=ProductionResultUpload.STATUS_APPLIED,
            )
            .order_by(
                ProductionResultUpload.production_stage.desc(),
                ProductionResultUpload.applied_at.desc(),
                ProductionResultUpload.id.desc(),
            )
            .all()
        )

    @classmethod
    def final_upload(cls, year, month):
        uploads = cls.applied_uploads(year, month)
        return uploads[0] if uploads else None

    @classmethod
    def quota_product_months(cls, months):
        """Detect stock-quota exemptions from official production results.

        A product is quota-exempt for a month only when the selected P2/P1
        workbook sets that product to target TL and exactly 100% in every
        region included by the workbook.  The marker is explanatory metadata;
        it never changes target, actual, priority, or premium calculations.
        """
        periods = tuple(sorted({(int(year), int(month)) for year, month in months}))
        uploads = {
            (year, month): cls.final_upload(year, month)
            for year, month in periods
        }
        selected = {period: upload for period, upload in uploads.items() if upload is not None}
        if not selected:
            return {}
        rows = ProductionRegionProductResult.query.filter(
            ProductionRegionProductResult.upload_id.in_([upload.id for upload in selected.values()])
        ).all()
        rows_by_upload = {}
        for row in rows:
            rows_by_upload.setdefault(int(row.upload_id), []).append(row)

        result = {}
        tolerance = Decimal("0.05")
        for period, upload in selected.items():
            upload_rows = rows_by_upload.get(int(upload.id), [])
            expected_regions = {str(row.region_code) for row in upload_rows}
            by_product = {}
            for row in upload_rows:
                by_product.setdefault(int(row.product_id), []).append(row)
            for product_id, product_rows in by_product.items():
                product_regions = {str(row.region_code) for row in product_rows}
                if not expected_regions or product_regions != expected_regions:
                    continue
                if all(
                    abs(cls._d(row.realization_percent) - Decimal("100")) <= tolerance
                    and abs(cls._d(row.actual_tl) - cls._d(row.target_tl)) <= tolerance
                    for row in product_rows
                ):
                    result.setdefault(product_id, []).append(period)
        return result

    @classmethod
    def final_product_result(cls, year, month, representative_id, product_id):
        for upload in cls.applied_uploads(year, month):
            result = ProductionResult.query.filter_by(
                upload_id=upload.id, representative_id=representative_id, product_id=product_id,
            ).first()
            if result is not None:
                return result
        return None

    @classmethod
    def effective_products(cls, year, month, representative_id, product_ids=None):
        """Resolve a whole representative period in a bounded query set.

        This is the batch equivalent of ``effective_product``.  It preserves
        product-specific P2 > P1 > IMS fallback, including the case where a P2
        upload exists but does not contain every product.  Production
        percentages are never capped at 100.
        """
        year, month, representative_id = int(year), int(month), int(representative_id)
        product_filter = {int(item) for item in product_ids or ()}

        target_query = Target.query.filter_by(
            year=year, month=month, representative_id=representative_id,
        )
        if product_filter:
            target_query = target_query.filter(Target.product_id.in_(product_filter))
        targets = target_query.all()
        targets_by_product = {int(target.product_id): target for target in targets}
        resolved_ids = product_filter or set(targets_by_product)
        if not resolved_ids:
            return {}

        summary_query = IMSSummary.query.filter_by(
            year=year, month=month, representative_id=representative_id,
        ).filter(IMSSummary.product_id.in_(resolved_ids))
        summaries = summary_query.all()
        summaries_by_product = {int(summary.product_id): summary for summary in summaries}

        uploads = cls.applied_uploads(year, month)
        upload_ids = [int(upload.id) for upload in uploads]
        production_by_key = {}
        if upload_ids:
            rows = ProductionResult.query.filter(
                ProductionResult.upload_id.in_(upload_ids),
                ProductionResult.representative_id == representative_id,
                ProductionResult.product_id.in_(resolved_ids),
            ).all()
            production_by_key = {
                (int(row.upload_id), int(row.product_id)): row for row in rows
            }

        resolved = {}
        for product_id in resolved_ids:
            target = targets_by_product.get(product_id)
            target_tl = cls._d(target.tl_target if target else 0)
            target_unit = cls._d(target.unit_target if target else 0)
            selected_upload = None
            selected_result = None
            for upload in uploads:
                selected_result = production_by_key.get((int(upload.id), product_id))
                if selected_result is not None:
                    selected_upload = upload
                    break

            if selected_result is not None:
                # IMS/BAKİYE targets remain the approved target master. A
                # production file contributes final outputs, never a target revision.
                percent = cls._d(selected_result.actual_tl) * Decimal("100") / target_tl if target_tl and selected_result.actual_tl is not None else cls._d(selected_result.realization_percent)
                actual_tl = cls._d(selected_result.actual_tl) if selected_result.actual_tl is not None else target_tl * percent / Decimal("100")
                actual_unit = cls._d(selected_result.actual_unit) if selected_result.actual_unit is not None else target_unit * percent / Decimal("100")
                resolved[product_id] = {
                    "source": f"PRODUCTION_{selected_upload.production_stage}",
                    "complete": True,
                    "target_tl": target_tl,
                    "target_unit": target_unit,
                    "realization_percent": percent,
                    "actual_tl": actual_tl,
                    "actual_unit": actual_unit,
                }
                continue

            summary = summaries_by_product.get(product_id)
            actual_tl = cls._d(summary.tl if summary else 0)
            actual_unit = cls._d(summary.unit if summary else 0)
            percent = (actual_tl / target_tl * Decimal("100")) if target_tl else Decimal("0")
            resolved[product_id] = {
                "source": "IMS",
                "complete": summary is not None,
                "target_tl": target_tl,
                "target_unit": target_unit,
                "realization_percent": percent,
                "actual_tl": actual_tl,
                "actual_unit": actual_unit,
            }
        return resolved

    @classmethod
    @contextmanager
    def use_effective_batch(cls, year, month, representative_id, rows):
        """Expose one pre-resolved batch only inside the current execution context."""
        payload = {
            "key": (int(year), int(month), int(representative_id)),
            "rows": rows,
        }
        token = cls._effective_batch_override.set(payload)
        try:
            yield rows
        finally:
            cls._effective_batch_override.reset(token)

    @classmethod
    def effective_product(cls, year, month, representative_id, product_id):
        override = cls._effective_batch_override.get()
        key = (int(year), int(month), int(representative_id))
        if override and override.get("key") == key:
            row = (override.get("rows") or {}).get(int(product_id))
            if row is not None:
                return row

        target = Target.query.filter_by(
            year=year, month=month, representative_id=representative_id, product_id=product_id,
        ).first()
        target_tl = cls._d(target.tl_target if target else 0)
        target_unit = cls._d(target.unit_target if target else 0)

        for upload in cls.applied_uploads(year, month):
            result = ProductionResult.query.filter_by(
                upload_id=upload.id, representative_id=representative_id, product_id=product_id,
            ).first()
            if result is None:
                continue
            percent = cls._d(result.actual_tl) * Decimal("100") / target_tl if target_tl and result.actual_tl is not None else cls._d(result.realization_percent)
            actual_tl = cls._d(result.actual_tl) if result.actual_tl is not None else target_tl * percent / Decimal("100")
            actual_unit = cls._d(result.actual_unit) if result.actual_unit is not None else target_unit * percent / Decimal("100")
            return {
                "source": f"PRODUCTION_{upload.production_stage}",
                "complete": True,
                "target_tl": target_tl,
                "target_unit": target_unit,
                "realization_percent": percent,
                "actual_tl": actual_tl,
                "actual_unit": actual_unit,
            }

        summary = IMSSummary.query.filter_by(
            year=year, month=month, representative_id=representative_id, product_id=product_id,
        ).first()
        actual_tl = cls._d(summary.tl if summary else 0)
        actual_unit = cls._d(summary.unit if summary else 0)
        percent = (actual_tl / target_tl * Decimal("100")) if target_tl else Decimal("0")
        return {
            "source": "IMS",
            "complete": summary is not None,
            "target_tl": target_tl,
            "target_unit": target_unit,
            "realization_percent": percent,
            "actual_tl": actual_tl,
            "actual_unit": actual_unit,
        }

    @classmethod
    def effective_representative(cls, year, month, representative_id):
        targets = Target.query.filter_by(year=year, month=month, representative_id=representative_id).all()
        rows = [cls.effective_product(year, month, representative_id, target.product_id) for target in targets]
        complete = bool(rows) and all(row["complete"] for row in rows)
        total_target = sum((row["target_tl"] for row in rows), Decimal("0"))
        total_actual = sum((row["actual_tl"] for row in rows), Decimal("0"))
        return {
            "complete": complete,
            "source": cls._source_name(year, month),
            "target_tl": total_target,
            "actual_tl": total_actual,
            "realization_percent": (total_actual / total_target * Decimal("100")) if total_target else Decimal("0"),
            "products": rows,
        }

    @classmethod
    def _source_name(cls, year, month):
        upload = cls.final_upload(year, month)
        return f"PRODUCTION_{upload.production_stage}" if upload else "IMS"
