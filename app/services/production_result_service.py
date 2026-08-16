from decimal import Decimal

from app.models import IMSSummary, ProductionResult, ProductionResultUpload, Target


class ProductionResultService:
    """Single source of truth for accepted period realizations.

    Priority is evaluated per representative/product with no waiting state:
    production 2 > production 1 > IMS. Production percentages are final, may
    exceed 100, and exact stored TL/unit targets are never rounded or rebuilt.
    """

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
    def final_product_result(cls, year, month, representative_id, product_id):
        for upload in cls.applied_uploads(year, month):
            result = ProductionResult.query.filter_by(
                upload_id=upload.id, representative_id=representative_id, product_id=product_id,
            ).first()
            if result is not None:
                return result
        return None

    @classmethod
    def effective_product(cls, year, month, representative_id, product_id):
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
            percent = cls._d(result.realization_percent)
            return {
                "source": f"PRODUCTION_{upload.production_stage}",
                "complete": True,
                "target_tl": target_tl,
                "target_unit": target_unit,
                "realization_percent": percent,
                "actual_tl": target_tl * percent / Decimal("100"),
                "actual_unit": target_unit * percent / Decimal("100"),
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
