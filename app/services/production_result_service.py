from decimal import Decimal

from app.models import IMSSummary, ProductionResult, ProductionResultUpload, Target


class ProductionResultService:
    """Single source of truth for accepted period realizations.

    Applied nationwide source priority: production 2 > production 1 > IMS.
    Production product percentages are authoritative, may exceed 100, and are
    converted to TL contribution using the exact stored product TL target.
    No percentage or target is rounded in this service.
    """

    @staticmethod
    def _d(value):
        return Decimal(str(value or 0))

    @classmethod
    def final_upload(cls, year, month):
        return (
            ProductionResultUpload.query.filter_by(
                year=year,
                month=month,
                status=ProductionResultUpload.STATUS_APPLIED,
            )
            .order_by(
                ProductionResultUpload.production_stage.desc(),
                ProductionResultUpload.applied_at.desc(),
                ProductionResultUpload.id.desc(),
            )
            .first()
        )

    @classmethod
    def final_product_result(cls, year, month, representative_id, product_id):
        upload = cls.final_upload(year, month)
        if upload is None:
            return None
        return ProductionResult.query.filter_by(
            upload_id=upload.id,
            representative_id=representative_id,
            product_id=product_id,
        ).first()

    @classmethod
    def effective_product(cls, year, month, representative_id, product_id):
        """Return exact accepted realization for one product.

        If production exists, its percentage is final. Otherwise IMS remains
        the current source. A missing production row is not silently replaced
        with IMS inside a production nationwide snapshot; it is reported as
        missing so validation can reject incomplete production imports.
        """
        target = Target.query.filter_by(
            year=year, month=month,
            representative_id=representative_id, product_id=product_id,
        ).first()
        target_tl = cls._d(target.tl_target if target else 0)
        target_unit = cls._d(target.unit_target if target else 0)
        upload = cls.final_upload(year, month)
        if upload is not None:
            result = ProductionResult.query.filter_by(
                upload_id=upload.id,
                representative_id=representative_id,
                product_id=product_id,
            ).first()
            if result is None:
                return {
                    "source": f"PRODUCTION_{upload.production_stage}",
                    "complete": False,
                    "target_tl": target_tl,
                    "target_unit": target_unit,
                    "realization_percent": None,
                    "actual_tl": None,
                }
            percent = cls._d(result.realization_percent)
            return {
                "source": f"PRODUCTION_{upload.production_stage}",
                "complete": True,
                "target_tl": target_tl,
                "target_unit": target_unit,
                "realization_percent": percent,
                "actual_tl": target_tl * percent / Decimal("100"),
            }

        summary = IMSSummary.query.filter_by(
            year=year, month=month,
            representative_id=representative_id, product_id=product_id,
        ).first()
        actual_tl = cls._d(summary.tl if summary else 0)
        percent = (actual_tl / target_tl * Decimal("100")) if target_tl else Decimal("0")
        return {
            "source": "IMS",
            "complete": summary is not None,
            "target_tl": target_tl,
            "target_unit": target_unit,
            "realization_percent": percent,
            "actual_tl": actual_tl,
        }

    @classmethod
    def effective_representative(cls, year, month, representative_id):
        """Calculate representative TL realization from exact product weights."""
        targets = Target.query.filter_by(
            year=year, month=month, representative_id=representative_id,
        ).all()
        rows = [
            cls.effective_product(year, month, representative_id, target.product_id)
            for target in targets
        ]
        complete = bool(rows) and all(row["complete"] for row in rows)
        total_target = sum((row["target_tl"] for row in rows), Decimal("0"))
        if not complete:
            return {
                "complete": False,
                "source": cls._source_name(year, month),
                "target_tl": total_target,
                "actual_tl": None,
                "realization_percent": None,
                "products": rows,
            }
        total_actual = sum((row["actual_tl"] for row in rows), Decimal("0"))
        total_percent = (total_actual / total_target * Decimal("100")) if total_target else Decimal("0")
        return {
            "complete": True,
            "source": cls._source_name(year, month),
            "target_tl": total_target,
            "actual_tl": total_actual,
            "realization_percent": total_percent,
            "products": rows,
        }

    @classmethod
    def _source_name(cls, year, month):
        upload = cls.final_upload(year, month)
        return f"PRODUCTION_{upload.production_stage}" if upload else "IMS"
