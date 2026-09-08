"""Fail-closed guards for switching the active IMS generation."""
from sqlalchemy import desc

from app.extensions import db
from app.models import ProductionResultUpload


class IMSRollbackGuard:
    @classmethod
    def final_applied_id(cls, year: int, month: int) -> int:
        upload_id = db.session.query(ProductionResultUpload.id).filter(
            ProductionResultUpload.year == int(year),
            ProductionResultUpload.month == int(month),
            ProductionResultUpload.status == ProductionResultUpload.STATUS_APPLIED,
        ).order_by(
            desc(ProductionResultUpload.production_stage),
            desc(ProductionResultUpload.uploaded_at),
            desc(ProductionResultUpload.id),
        ).limit(1).scalar()
        return int(upload_id or 0)

    @classmethod
    def assert_period_open(cls, year: int, month: int) -> None:
        if cls.final_applied_id(year, month):
            raise RuntimeError("Üretim sonucu ile kapanmış IMS dönemi geri alınamaz.")
