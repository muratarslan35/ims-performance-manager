"""Atomically roll back the known wrong Week 33 upload to safe Week 32."""
from __future__ import annotations

import json

from app import create_app
from app.extensions import db
from app.models import IMSImportJob, IMSUpload
from app.services.ims_progress_store import IMSProgressStore
from app.services.ims_upload_lifecycle_service import IMSUploadLifecycleService
from app.services.period_service import PeriodService
from config import Config


def main() -> int:
    app = create_app(Config)
    with app.app_context():
        wrong = db.session.get(IMSUpload, 46)
        previous = db.session.get(IMSUpload, 45)
        if wrong is None or previous is None:
            raise SystemExit("WEEK33_ROLLBACK_REFUSED|reason=expected_uploads_missing")
        if (wrong.year, wrong.month, wrong.week_number, wrong.status) != (2026, 8, 33, "COMPLETED"):
            raise SystemExit("WEEK33_ROLLBACK_REFUSED|reason=wrong_upload_identity_mismatch")
        if (previous.year, previous.month, previous.week_number, previous.status) != (2026, 8, 32, "COMPLETED"):
            raise SystemExit("WEEK33_ROLLBACK_REFUSED|reason=week32_identity_mismatch")

        # The import was accepted but never published. Seal its already
        # captured rollback journal immediately before consuming it.
        IMSUploadLifecycleService.seal_snapshot_master_state(upload_id=wrong.id)
        result = IMSUploadLifecycleService.rollback_to_previous(
            wrong.id, actor="GitHub production wrong-file rollback"
        )
        job = IMSImportJob.query.filter_by(ims_upload_id=wrong.id).order_by(
            IMSImportJob.id.desc()
        ).first()
        if job is not None:
            try:
                summary = json.loads(job.result_summary or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                summary = {}
            summary["publication_ready"] = False
            summary["rolled_back_wrong_source"] = True
            summary["active_upload_id"] = previous.id
            job.result_summary = json.dumps(summary, ensure_ascii=False, default=str)
            db.session.commit()
            IMSProgressStore.write(
                job.id, percent=100, stage="rolled_back",
                message="Hatalı IMS geri alındı",
                detail="32. hafta yeniden aktif",
                status=IMSImportJob.STATUS_COMPLETED,
            )

        period = PeriodService.get_active_period()
        if int(period.get("upload_id") or 0) != 45 or int(period.get("week_number") or 0) != 32:
            raise RuntimeError(f"Week 32 active-period verification failed: {period}")
        rollback_available, rollback_reason = IMSUploadLifecycleService.can_rollback(previous)
        if not rollback_available:
            raise RuntimeError(f"Week 32 rollback button is unavailable: {rollback_reason}")
        print(
            "WEEK33_WRONG_FILE_ROLLBACK|PASS|"
            f"rolled_back={result['rolled_back_upload_id']}|active={result['active_upload_id']}|"
            "week=32|previous_ims_button=VISIBLE"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
