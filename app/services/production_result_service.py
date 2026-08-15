from app.models import ProductionRepresentativeTotal
from app.models import ProductionResult
from app.models import ProductionResultUpload


class ProductionResultService:
    """Resolve final production realizations without mutating source IMS rows."""

    @staticmethod
    def _applied_uploads(year, month):
        return (
            ProductionResultUpload.query.filter_by(
                year=year,
                month=month,
                status=ProductionResultUpload.STATUS_APPLIED,
            )
            .order_by(ProductionResultUpload.production_stage.desc(), ProductionResultUpload.applied_at.desc())
        )

    @classmethod
    def final_product_result(cls, year, month, representative_id, product_id):
        row = (
            ProductionResult.query.join(ProductionResultUpload)
            .filter(
                ProductionResultUpload.year == year,
                ProductionResultUpload.month == month,
                ProductionResultUpload.status == ProductionResultUpload.STATUS_APPLIED,
                ProductionResult.representative_id == representative_id,
                ProductionResult.product_id == product_id,
            )
            .order_by(ProductionResultUpload.production_stage.desc(), ProductionResultUpload.applied_at.desc())
            .first()
        )
        return row

    @classmethod
    def final_representative_total(cls, year, month, representative_id):
        row = (
            ProductionRepresentativeTotal.query.join(ProductionResultUpload)
            .filter(
                ProductionResultUpload.year == year,
                ProductionResultUpload.month == month,
                ProductionResultUpload.status == ProductionResultUpload.STATUS_APPLIED,
                ProductionRepresentativeTotal.representative_id == representative_id,
            )
            .order_by(ProductionResultUpload.production_stage.desc(), ProductionResultUpload.applied_at.desc())
            .first()
        )
        return row
