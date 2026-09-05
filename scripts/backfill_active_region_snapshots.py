"""Build/reuse the durable manager-region snapshot set for the latest IMS period."""
from __future__ import annotations

from sqlalchemy import desc

from app import create_app
from app.extensions import db
from app.models import IMSUpload
from app.services.persistent_region_snapshot_service import PersistentRegionSnapshotService


def main():
    app = create_app()
    with app.app_context():
        latest = IMSUpload.query.filter_by(status="COMPLETED").order_by(
            desc(IMSUpload.year),
            desc(IMSUpload.month),
            desc(IMSUpload.week_number),
            desc(IMSUpload.completed_at),
            desc(IMSUpload.id),
        ).first()
        if latest is None:
            print("REGION_SNAPSHOT_BACKFILL|status=SKIPPED|reason=NO_COMPLETED_IMS")
            return 0

        def progress(done, total, name):
            print(f"REGION_SNAPSHOT_BACKFILL_PROGRESS|{done}/{total}|{name}", flush=True)

        result = PersistentRegionSnapshotService.build_for_period(
            latest.year,
            latest.month,
            progress=progress,
        )
        print(
            "REGION_SNAPSHOT_BACKFILL|"
            f"status={result.get('status')}|year={latest.year}|month={latest.month}|"
            f"upload_id={latest.id}|regions={result.get('regions', 0)}|"
            f"set_id={result.get('set_id', 0)}"
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
