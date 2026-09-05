"""Single-process worker for persistent IMS import jobs.

Worker restarts also re-run the latest durable region-snapshot warm-up. This is
intentional: import-mode production activation is the recovery path after a
snapshot persistence fix, while queued IMS imports still keep priority.
"""
import signal
import time

from sqlalchemy import desc

from app import create_app
from app.extensions import db
from app.models import IMSImportJob, IMSUpload
from app.services.ims_import_queue import IMSImportQueue
from app.services.persistent_region_snapshot_service import PersistentRegionSnapshotService


stopping = False


def _stop(*_args):
    global stopping
    stopping = True


def _backfill_latest_region_snapshots(app):
    """Warm the active IMS generation after deploy/restart without blocking imports.

    Existing deployments may predate the persistent snapshot feature. A worker
    restart therefore creates the latest region set once. If an IMS job is
    already queued, skip this warm-up: that import has priority and will publish
    its own snapshot set when it completes.
    """
    queued = IMSImportJob.query.filter(
        IMSImportJob.status == IMSImportJob.STATUS_QUEUED
    ).first()
    if queued is not None:
        app.logger.info("region_snapshot_startup_backfill skipped=queued_import job_id=%s", queued.id)
        return

    latest = IMSUpload.query.filter_by(status="COMPLETED").order_by(
        desc(IMSUpload.year),
        desc(IMSUpload.month),
        desc(IMSUpload.week_number),
        desc(IMSUpload.completed_at),
        desc(IMSUpload.id),
    ).first()
    if latest is None:
        return
    try:
        result = PersistentRegionSnapshotService.build_for_period(latest.year, latest.month)
        app.logger.info(
            "region_snapshot_startup_backfill status=%s year=%s month=%s regions=%s set_id=%s",
            result.get("status"), latest.year, latest.month,
            result.get("regions", 0), result.get("set_id", 0),
        )
    except Exception:
        db.session.rollback()
        app.logger.exception(
            "region_snapshot_startup_backfill_failed year=%s month=%s upload_id=%s",
            latest.year, latest.month, latest.id,
        )
    finally:
        db.session.remove()


def main():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    app = create_app()
    with app.app_context():
        IMSImportQueue.recover_stale()
        _backfill_latest_region_snapshots(app)
        while not stopping:
            job = IMSImportQueue.claim_next()
            if job is None:
                db.session.remove()
                time.sleep(2)
                continue
            IMSImportQueue.process(job)
            db.session.remove()


if __name__ == "__main__":
    main()
