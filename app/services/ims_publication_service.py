"""Gate IMS visibility until every durable read model is ready."""
from __future__ import annotations

import json

import sqlalchemy as sa
from sqlalchemy import desc

from app.extensions import db
from app.models import IMSImportJob, IMSUpload
from app.services.ims_progress_store import IMSProgressStore


ims_publication_receipts = sa.Table(
    "ims_publication_receipts",
    db.metadata,
    sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("upload_id", sa.Integer, sa.ForeignKey("ims_uploads.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("dismissed_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
)


class IMSPublicationService:
    @classmethod
    def ensure_schema(cls):
        ims_publication_receipts.create(bind=db.engine, checkfirst=True)

    @classmethod
    def pending_job(cls, year=None, month=None):
        query = IMSImportJob.query.filter(
            IMSImportJob.status.in_((IMSImportJob.STATUS_QUEUED, IMSImportJob.STATUS_PROCESSING, IMSImportJob.STATUS_COMPLETED))
        )
        if year is not None:
            query = query.filter(IMSImportJob.year == int(year))
        if month is not None:
            query = query.filter(IMSImportJob.month == int(month))
        for job in query.order_by(desc(IMSImportJob.queued_at), desc(IMSImportJob.id)).limit(5):
            progress = IMSProgressStore.for_job(job)
            if progress.get("status") in {IMSImportJob.STATUS_QUEUED, IMSImportJob.STATUS_PROCESSING}:
                return job
            if progress.get("stage") in {"read_models", "dashboard_snapshot", "region_snapshots", "representative_snapshots", "snapshot_retry"}:
                return job
        return None

    @classmethod
    def latest_visible_upload(cls, year=None, month=None):
        query = IMSUpload.query.filter(IMSUpload.status == IMSUpload.STATUS_COMPLETED)
        if year is not None:
            query = query.filter(IMSUpload.year == int(year))
        if month is not None:
            query = query.filter(IMSUpload.month == int(month))
        uploads = query.order_by(
            desc(IMSUpload.year), desc(IMSUpload.month), desc(IMSUpload.week_number),
            desc(IMSUpload.completed_at), desc(IMSUpload.id),
        ).limit(5).all()
        pending = cls.pending_job(year, month)
        pending_upload_id = int(pending.ims_upload_id) if pending and pending.ims_upload_id else None
        pending_progress = IMSProgressStore.for_job(pending) if pending else {}
        committed_unlinked_stages = {
            "commit_upload", "final_checks", "read_models", "dashboard_snapshot",
            "region_snapshots", "representative_snapshots", "snapshot_retry",
        }
        if (
            pending
            and pending_upload_id is None
            and uploads
            and pending_progress.get("stage") in committed_unlinked_stages
        ):
            # The import has committed its IMS row but has not linked the queue row
            # yet; the newest row belongs to that still-unpublished job.
            uploads = uploads[1:]
        elif pending_upload_id is not None:
            uploads = [item for item in uploads if int(item.id) != pending_upload_id]
        return uploads[0] if uploads else None

    @classmethod
    def latest_ready_job(cls):
        for job in IMSImportJob.query.filter_by(status=IMSImportJob.STATUS_COMPLETED).order_by(
            desc(IMSImportJob.completed_at), desc(IMSImportJob.id)
        ).limit(10):
            try:
                summary = json.loads(job.result_summary or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                summary = {}
            if summary.get("publication_ready") is True:
                return job
        return None

    @classmethod
    def notice_for_user(cls, user_id):
        cls.ensure_schema()
        job = cls.latest_ready_job()
        upload = db.session.get(IMSUpload, int(job.ims_upload_id)) if job and job.ims_upload_id else None
        if upload is None:
            # Uploads completed before the atomic-publication marker was added
            # are still eligible once no import/snapshot publication is pending.
            upload = cls.latest_visible_upload()
        if upload is None:
            return None
        seen = db.session.execute(sa.select(ims_publication_receipts.c.user_id).where(
            ims_publication_receipts.c.user_id == int(user_id),
            ims_publication_receipts.c.upload_id == int(upload.id),
        )).scalar()
        if seen:
            return None
        return {
            "upload_id": int(upload.id), "year": int(upload.year), "month": int(upload.month),
            "week_number": int(upload.week_number or 0), "file_name": upload.file_name,
        }

    @classmethod
    def dismiss(cls, user_id, upload_id):
        cls.ensure_schema()
        if db.session.execute(sa.select(ims_publication_receipts.c.user_id).where(
            ims_publication_receipts.c.user_id == int(user_id),
            ims_publication_receipts.c.upload_id == int(upload_id),
        )).scalar() is None:
            db.session.execute(ims_publication_receipts.insert().values(
                user_id=int(user_id), upload_id=int(upload_id)
            ))
            db.session.commit()
