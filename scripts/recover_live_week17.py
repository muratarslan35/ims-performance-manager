"""One-shot production recovery guard for reverting the live IMS state to week 17.

The script is intentionally fail-closed. It may cancel stale queue rows, remove
an existing completed week-18 upload through the normal lifecycle service,
rebuild a missing week-17 period summary from the still-intact week-17 facts,
and remove only representative masters that were created *after* week 17 and
have no protected history outside the current period. Existing historical or
inactive representatives are never removed merely because they are inactive.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import sqlalchemy as sa

from app import create_app
from app.extensions import db
from app.models import (
    IMSFact,
    IMSImportJob,
    IMSRawData,
    IMSSummary,
    IMSUpload,
    Representative,
    RepresentativeAlias,
    RepresentativeBrickAssignment,
    Target,
)
from app.services.ims_import_service import IMSImportService
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


def _protected_representative_ids(candidate_ids: list[int], year: int, month: int) -> set[int]:
    """Resolve protected representative IDs with one grouped query per FK.

    Current-period Target/Summary/Brick rows may belong to the bad workbook, so
    those exact-period references do not protect a newly-created master. Any
    reference outside that current period, or any other business-table FK,
    preserves the representative. This batch form avoids thousands of full-table
    COUNT scans on the production database.
    """
    ids = sorted({int(value) for value in candidate_ids})
    if not ids:
        return set()

    protected: set[int] = set()
    rep_table = Representative.__table__
    for table in db.metadata.sorted_tables:
        if table.name in {rep_table.name, "representative_aliases"}:
            continue
        rep_columns = [
            fk.parent
            for fk in table.foreign_keys
            if fk.column.table.name == rep_table.name and fk.column.name == "id"
        ]
        for column in rep_columns:
            predicate = column.in_(ids)
            if table.name in {"targets", "ims_summary", "representative_brick_assignments"}:
                predicate = sa.and_(
                    predicate,
                    sa.not_(sa.and_(table.c.year == int(year), table.c.month == int(month))),
                )
            rows = db.session.execute(
                sa.select(column).where(predicate).distinct()
            ).scalars().all()
            protected.update(int(value) for value in rows if value is not None)
    return protected


def _remove_bad_import_orphan_representatives(latest: IMSUpload) -> tuple[list[dict], int]:
    """Remove only masters created after week 17 that have no protected history."""
    if latest.completed_at is None:
        raise RuntimeError("Week 17 completed_at is missing; representative cleanup refused.")

    candidates = (
        Representative.query
        .filter(Representative.created_at > latest.completed_at)
        .order_by(Representative.created_at.asc(), Representative.id.asc())
        .all()
    )
    protected_ids = _protected_representative_ids(
        [representative.id for representative in candidates], latest.year, latest.month
    )
    removed = []
    for representative in candidates:
        if int(representative.id) in protected_ids:
            continue

        Target.query.filter_by(
            representative_id=representative.id,
            year=latest.year,
            month=latest.month,
        ).delete(synchronize_session=False)
        IMSSummary.query.filter_by(
            representative_id=representative.id,
            year=latest.year,
            month=latest.month,
        ).delete(synchronize_session=False)
        RepresentativeBrickAssignment.query.filter_by(
            representative_id=representative.id,
            year=latest.year,
            month=latest.month,
        ).delete(synchronize_session=False)
        RepresentativeAlias.query.filter_by(
            representative_id=representative.id
        ).delete(synchronize_session=False)

        removed.append({
            "id": int(representative.id),
            "name": str(representative.rep_name),
            "code": str(representative.rep_code or ""),
            "created_at": representative.created_at.isoformat(),
        })
        db.session.delete(representative)

    if removed:
        db.session.commit()
    return removed, len(protected_ids)


def _rebuild_week17_summary(latest: IMSUpload) -> int:
    summary_count = IMSSummary.query.filter_by(year=latest.year, month=latest.month).count()
    if summary_count > 0:
        return int(summary_count)

    service = IMSImportService("week17-recovery-no-workbook.xlsx", uploaded_by="week17-recovery")
    service.upload = latest
    service.rebuild_summary(int(latest.year), int(latest.month))
    db.session.commit()
    return int(IMSSummary.query.filter_by(year=latest.year, month=latest.month).count())


def _orphan_upload_rows() -> dict[str, int]:
    upload_table = IMSUpload.__table__
    result = {}
    for model in (IMSRawData, IMSFact, IMSSummary):
        table = model.__table__
        if "upload_id" not in table.c:
            continue
        count = db.session.execute(
            sa.select(sa.func.count())
            .select_from(table.outerjoin(upload_table, table.c.upload_id == upload_table.c.id))
            .where(upload_table.c.id.is_(None))
        ).scalar_one()
        result[table.name] = int(count or 0)
    return result


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

        removed_representatives, protected_recent = _remove_bad_import_orphan_representatives(latest)
        summary_count = _rebuild_week17_summary(latest)

        raw_count = IMSRawData.query.filter_by(upload_id=latest.id).count()
        fact_count = IMSFact.query.filter_by(upload_id=latest.id).count()
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
        orphan_rows = _orphan_upload_rows()
        orphan_total = sum(orphan_rows.values())

        recent = []
        if latest.completed_at is not None:
            recent = Representative.query.filter(Representative.created_at > latest.completed_at).all()
        protected_after = _protected_representative_ids(
            [representative.id for representative in recent], latest.year, latest.month
        )
        current_recent_orphans = sum(
            1 for representative in recent if int(representative.id) not in protected_after
        )

        if remaining_week18 or active_jobs or orphan_total or current_recent_orphans:
            raise RuntimeError(
                "Recovery post-check failed: "
                f"week18={remaining_week18} active_jobs={active_jobs} "
                f"orphan_upload_rows={orphan_rows} recent_orphan_reps={current_recent_orphans}."
            )

        print(f"BAD_IMPORT_REPRESENTATIVES_REMOVED|count={len(removed_representatives)}|rows={removed_representatives}")
        print(f"RECENT_REPRESENTATIVES_PROTECTED_BY_HISTORY|count={protected_recent}")
        print(f"ORPHAN_UPLOAD_ROWS|{orphan_rows}")
        print(
            "WEEK17_RECOVERY|PASS|"
            f"upload_id={latest.id}|year={latest.year}|month={latest.month}|week={latest.week_number}|"
            f"raw={raw_count}|facts={fact_count}|summaries={summary_count}|"
            f"cancelled_jobs={cancelled}|deleted_week18={removed_week18}|"
            f"removed_bad_import_reps={len(removed_representatives)}|"
            f"protected_recent_reps={protected_recent}|"
            f"cleared_dashboard_snapshots={stale_dashboard_files}"
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
