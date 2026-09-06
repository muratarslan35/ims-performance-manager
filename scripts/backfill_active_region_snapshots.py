"""Build/reuse the durable manager-region snapshot set for the latest IMS period."""
from __future__ import annotations

import argparse

from sqlalchemy import desc

from app import create_app
from app.extensions import db
from app.models import IMSUpload
from app.services.persistent_region_snapshot_service import (
    PersistentRegionSnapshotService,
    region_snapshot_sets,
    region_snapshots,
)


def _drop_current_snapshot_set(year: int, month: int) -> int | None:
    """Delete only the exact current-source snapshot generation.

    Backend/heavy deploys call this after calculation code changes so a payload
    created by older code can never be silently reused. Raw IMS, targets and
    production business data are untouched.
    """
    ims_id, production_id = PersistentRegionSnapshotService.source_identity(year, month)
    if not ims_id:
        return None
    existing = PersistentRegionSnapshotService._existing_set(
        year, month, ims_id, production_id
    )
    if not existing:
        return None

    set_id = int(existing.id)
    db.session.execute(region_snapshots.delete().where(region_snapshots.c.set_id == set_id))
    db.session.execute(region_snapshot_sets.delete().where(region_snapshot_sets.c.id == set_id))
    db.session.commit()
    return set_id


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild the latest snapshot even when the IMS source identity did not change.",
    )
    args = parser.parse_args(argv)

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

        if args.force:
            removed_set_id = _drop_current_snapshot_set(latest.year, latest.month)
            print(
                "REGION_SNAPSHOT_INVALIDATION|"
                f"mode=force|year={latest.year}|month={latest.month}|"
                f"removed_set_id={removed_set_id or 0}",
                flush=True,
            )

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
            f"set_id={result.get('set_id', 0)}|force={int(args.force)}"
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
