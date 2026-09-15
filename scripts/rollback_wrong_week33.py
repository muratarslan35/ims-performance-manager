"""Atomically roll back the known wrong Week 33 upload to safe Week 32."""
from __future__ import annotations

import json
from datetime import datetime

from app import create_app
from app.extensions import db
from app.models import AuditLog, IMSImportJob, IMSUpload
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
        payload = IMSUploadLifecycleService._validated_snapshot_payload(wrong, previous.id)
        try:
            IMSUploadLifecycleService._restore_period_snapshot(wrong)
            master_result = IMSUploadLifecycleService._restore_master_state(payload)
            wrong.status = IMSUpload.STATUS_ROLLED_BACK
            db.session.add(AuditLog(
                username="GitHub production wrong-file rollback",
                module="IMS",
                action=(
                    "IMS_WRONG_SOURCE_ROLLBACK from_upload=46 to_upload=45 "
                    f"period=2026-08 master_representatives={master_result['representatives']} "
                    f"master_products={master_result['products']}"
                ),
                created_at=datetime.utcnow(),
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        IMSUploadLifecycleService._invalidate_runtime_caches(2026, 8)
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
        print(
            "WEEK33_WRONG_FILE_ROLLBACK|PASS|"
            "rolled_back=46|active=45|week=32"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
