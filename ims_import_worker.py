"""Single-process worker for persistent IMS import jobs.

Worker restarts also re-run durable read-model warm-ups. Import jobs still keep
priority; once a workbook finishes, the national dashboard is rebuilt once in
the worker and atomically shared with every Gunicorn worker.
"""
import signal
import time

from sqlalchemy import desc

from app import create_app
from app.cache.dashboard_cache import DashboardCache
from app.constants.dashboard_constants import DashboardConstants
from app.extensions import db
from app.models import IMSImportJob, IMSUpload
from app.services.dashboard_service import DashboardService
from app.services.ims_import_queue import IMSImportQueue
from app.services.persistent_dashboard_snapshot_service import PersistentDashboardSnapshotService
from app.services.persistent_region_snapshot_service import PersistentRegionSnapshotService


stopping = False


def _stop(*_args):
    global stopping
    stopping = True


def _warm_dashboard_snapshot(app, year, month):
    """Build one canonical dashboard payload and publish it cross-worker."""
    started = time.monotonic()
    try:
        cache_key = DashboardConstants.CACHE_KEY_TEMPLATE.format(
            year=int(year), month=int(month), rep_id=None
        )
        DashboardCache().invalidate(cache_key)
        payload = DashboardService(year=int(year), month=int(month)).run()
        result = PersistentDashboardSnapshotService.publish(year, month, payload)
        app.logger.info(
            "dashboard_snapshot_warm status=%s year=%s month=%s ims_upload_id=%s seconds=%.3f",
            result.get("status"), year, month, result.get("ims_upload_id", 0),
            time.monotonic() - started,
        )
        return result
    except Exception:
        db.session.rollback()
        app.logger.exception("dashboard_snapshot_warm_failed year=%s month=%s", year, month)
        return {"status": "FAILED"}
    finally:
        db.session.remove()


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
        _warm_dashboard_snapshot(app, latest.year, latest.month)
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
            job_id = job.id
            job_year = job.year
            job_month = job.month
            IMSImportQueue.process(job)
            completed = db.session.get(IMSImportJob, job_id)
            if completed is not None and completed.status == IMSImportJob.STATUS_COMPLETED:
                _warm_dashboard_snapshot(app, job_year, job_month)
            db.session.remove()


if __name__ == "__main__":
    main()
