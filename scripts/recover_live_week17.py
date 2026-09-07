"""One-shot production recovery guard for reverting the live IMS state to week 17.

The script is intentionally fail-closed. It may cancel stale queue rows and remove
an existing completed week-18 upload through the normal lifecycle service, but it
will not touch any other completed IMS history. It then verifies that week 17 is
the newest completed IMS and clears only the durable national dashboard snapshot
JSON files so the next page load rebuilds against week 17.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app import create_app
from app.extensions import db
from app.models import IMSFact, IMSImportJob, IMSRawData, IMSSummary, IMSUpload
from app.services.ims_upload_lifecycle_service import IMSUploadLifecycleService
from app.services.period_service import PeriodService

TARGET_WEEK = 17
REMOVED_WEEK = 18


def _completed_uploads():
    return (
        IMSUpload.query.filter_by(status="COMPLETED")
        .order_by(
            IMSUpload.year.desc(),
            IMSUpload.month.desc(),
            IMSUpload.week_number.desc(),
            IMSUpload.completed_at.desc(),
            IMSUpload.id.desc(),
        )
        .all()
    )


def _cancel_active_jobs() -> int:
    jobs = IMSImportJob.query.filter(
        IMSImportJob.status.in_((IMSImportJob.STATUS_QUEUED, IMSImportJob.STATUS_PROCESSING))
    ).all()
    now = datetime.utcnow()
    for job in jobs:
        job.status = IMSImportJob.STATUS_FAILED
        if hasattr(job, "error_message"):
            job.error_message = "17. hafta güvenli geri dönüşü nedeniyle durduruldu."
        if hasattr(job, "completed_at"):
            job.completed_at = now
        if hasattr(job, "heartbeat_at"):
            job.heartbeat_at = now
    if jobs:
        db.session.commit()
    return len(jobs)


def _delete_week18_if_present() -> list[int]:
    removed = []
    while True:
        current = _completed_uploads()
        week18 = next((u for u in current if int(u.week_number or 0) == REMOVED_WEEK), None)
        if week18 is None:
            break
        latest = current[0] if current else None
        if latest is None or latest.id != week18.id:
            raise RuntimeError(
                f"Week 18 upload {week18.id} is not the newest completed IMS; automatic deletion refused."
            )
        allowed, reason = IMSUploadLifecycleService.can_delete(week18)
        if not allowed:
            raise RuntimeError(reason or "Week 18 cannot be safely deleted.")
        IMSUploadLifecycleService.delete_upload(week18.id)
        removed.append(int(week18.id))
    return removed


def _clear_dashboard_snapshots(instance_path: str) -> int:
    root = Path(instance_path) / "dashboard_snapshots"
    if not root.exists():
        return 0
    removed = 0
    for path in root.glob("dashboard-*.json"):
        path.unlink(missing_ok=True)
        removed += 1
    for path in root.glob("dashboard-*.json.tmp-*"):
        path.unlink(missing_ok=True)
    return removed


def main() -> int:
    app = create_app()
    with app.app_context():
        cancelled = _cancel_active_jobs()
        removed_week18 = _delete_week18_if_present()

        uploads = _completed_uploads()
        if not uploads:
            raise RuntimeError("No completed IMS upload remains after recovery.")
        latest = uploads[0]
        if int(latest.week_number or 0) != TARGET_WEEK:
            raise RuntimeError(
                "Recovery refused: newest completed IMS is "
                f"week={latest.week_number} id={latest.id}, expected week 17."
            )

        active = PeriodService.get_active_period()
        if int(active.get("upload_id") or 0) != int(latest.id):
            raise RuntimeError(
                f"Active period did not resolve to week 17 upload: active={active}, latest_id={latest.id}."
            )

        raw_count = IMSRawData.query.filter_by(upload_id=latest.id).count()
        fact_count = IMSFact.query.filter_by(upload_id=latest.id).count()
        summary_count = IMSSummary.query.filter_by(year=latest.year, month=latest.month).count()
        if raw_count <= 0 or fact_count <= 0 or summary_count <= 0:
            raise RuntimeError(
                "Week 17 business data is incomplete: "
                f"raw={raw_count} facts={fact_count} summaries={summary_count}."
            )

        stale_dashboard_files = _clear_dashboard_snapshots(app.instance_path)
        remaining_week18 = IMSUpload.query.filter_by(status="COMPLETED", week_number=REMOVED_WEEK).count()
        active_jobs = IMSImportJob.query.filter(
            IMSImportJob.status.in_((IMSImportJob.STATUS_QUEUED, IMSImportJob.STATUS_PROCESSING))
        ).count()
        if remaining_week18 or active_jobs:
            raise RuntimeError(
                f"Recovery post-check failed: week18={remaining_week18} active_jobs={active_jobs}."
            )

        print(
            "WEEK17_RECOVERY|PASS|"
            f"upload_id={latest.id}|year={latest.year}|month={latest.month}|week={latest.week_number}|"
            f"raw={raw_count}|facts={fact_count}|summaries={summary_count}|"
            f"cancelled_jobs={cancelled}|deleted_week18={removed_week18}|"
            f"cleared_dashboard_snapshots={stale_dashboard_files}"
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
