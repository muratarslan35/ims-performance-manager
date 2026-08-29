"""Keep Representative.active aligned with the latest completed IMS roster.

Only the active flag is changed. Historical targets, sales, summaries, assignments,
and prime data are never deleted or rewritten here.
"""
from __future__ import annotations

from sqlalchemy import desc, func

from app.extensions import db
from app.models import IMSRawData, IMSUpload, Representative


class IMSRosterSyncService:
    @staticmethod
    def latest_completed_upload():
        return (
            IMSUpload.query.filter(IMSUpload.status == "COMPLETED")
            .order_by(
                desc(IMSUpload.year),
                desc(IMSUpload.month),
                desc(func.coalesce(IMSUpload.week_number, 0)),
                desc(IMSUpload.completed_at),
                desc(IMSUpload.id),
            )
            .first()
        )

    @classmethod
    def sync_latest(cls):
        upload = cls.latest_completed_upload()
        if upload is None:
            return {
                "changed": 0,
                "activated": 0,
                "deactivated": 0,
                "active_roster": 0,
                "upload_id": None,
            }

        roster_ids = {
            int(row[0])
            for row in db.session.query(IMSRawData.representative_id)
            .filter(
                IMSRawData.upload_id == upload.id,
                IMSRawData.representative_id.isnot(None),
            )
            .distinct()
            .all()
            if row[0] is not None
        }

        # Fail closed: a completed upload with no resolved representatives must
        # never deactivate the entire master table because of a parser anomaly.
        if not roster_ids:
            raise RuntimeError(
                f"IMS roster sync refused: completed upload {upload.id} has no resolved representatives"
            )

        activated = 0
        deactivated = 0
        for representative in Representative.query.all():
            should_be_active = int(representative.id) in roster_ids
            if bool(representative.active) == should_be_active:
                continue
            representative.active = should_be_active
            if should_be_active:
                activated += 1
            else:
                deactivated += 1

        db.session.commit()
        return {
            "changed": activated + deactivated,
            "activated": activated,
            "deactivated": deactivated,
            "active_roster": len(roster_ids),
            "upload_id": int(upload.id),
            "year": int(upload.year),
            "month": int(upload.month),
            "week_number": int(upload.week_number) if upload.week_number is not None else None,
        }
