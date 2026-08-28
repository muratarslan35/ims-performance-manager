"""Authenticated live progress endpoint for IMS background imports."""
from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint
from flask_login import current_user, login_required

from app.models import IMSImportJob
from app.services.ims_progress_store import IMSProgressStore


ims_progress_bp = Blueprint("ims_progress", __name__, url_prefix="/ims")


@ims_progress_bp.route("/progress", methods=["GET"])
@login_required
def progress():
    jobs = (
        IMSImportJob.query
        .filter_by(uploaded_by=current_user.full_name)
        .order_by(IMSImportJob.queued_at.desc(), IMSImportJob.id.desc())
        .limit(10)
        .all()
    )
    active = next(
        (job for job in jobs if job.status in {IMSImportJob.STATUS_QUEUED, IMSImportJob.STATUS_PROCESSING}),
        None,
    )
    selected = active
    if selected is None:
        latest = jobs[0] if jobs else None
        if latest and latest.completed_at and latest.completed_at >= datetime.utcnow() - timedelta(minutes=15):
            selected = latest

    if selected is None:
        return {"active": False, "progress": None}

    payload = IMSProgressStore.for_job(selected)
    payload.update({
        "file_name": selected.file_name,
        "year": selected.year,
        "month": selected.month,
        "ims_upload_id": selected.ims_upload_id,
        "queued_at": selected.queued_at.isoformat() if selected.queued_at else None,
        "started_at": selected.started_at.isoformat() if selected.started_at else None,
        "completed_at": selected.completed_at.isoformat() if selected.completed_at else None,
    })
    return {
        "active": selected.status in {IMSImportJob.STATUS_QUEUED, IMSImportJob.STATUS_PROCESSING},
        "progress": payload,
    }
