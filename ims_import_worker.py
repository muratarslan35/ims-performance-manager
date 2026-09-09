"""Single-process worker for persistent IMS import jobs.

Worker restarts also re-run durable read-model warm-ups. Import jobs still keep
priority; once a workbook finishes, durable dashboard/region/representative read
models are prepared without waiting for a user's first page request.
"""
import signal
import time
import json
from collections import deque

from sqlalchemy import desc

from app import create_app
from app.cache.dashboard_cache import DashboardCache
from app.constants.dashboard_constants import DashboardConstants
from app.extensions import db
from app.models import IMSImportJob, IMSUpload
from app.services.dashboard_service import DashboardService
from app.services.ims_import_queue import IMSImportQueue
from app.services.ims_progress_store import IMSProgressStore
from app.services.import_roster_sync import IMSRosterSyncService
from app.services.ims_upload_lifecycle_service import IMSUploadLifecycleService
from app.services.persistent_dashboard_snapshot_service import PersistentDashboardSnapshotService
from app.services.persistent_region_snapshot_service import PersistentRegionSnapshotService
from app.services.persistent_representative_snapshot_service import PersistentRepresentativeSnapshotService


stopping = False


def _stop(*_args):
    global stopping
    stopping = True


def _warm_dashboard_snapshot(app, year, month):
    """Build/reuse one canonical dashboard payload across all processes."""
    started = time.monotonic()
    try:
        service = DashboardService(year=int(year), month=int(month))
        cache_key = DashboardConstants.CACHE_KEY_TEMPLATE.format(
            year=int(year), month=int(month), rep_id=None
        )

        def rebuild():
            DashboardCache().invalidate(cache_key)
            return service.run()

        _payload, built = PersistentDashboardSnapshotService.get_or_build(
            year, month, rebuild
        )
        ims_id, production_id = PersistentDashboardSnapshotService.source_identity(year, month)
        result = {
            "status": "ACTIVE" if built else "REUSED",
            "ims_upload_id": ims_id,
            "production_upload_id": production_id,
        }
        app.logger.info(
            "dashboard_snapshot_warm status=%s year=%s month=%s ims_upload_id=%s seconds=%.3f",
            result["status"], year, month, ims_id, time.monotonic() - started,
        )

        read_started = time.perf_counter()
        verified = PersistentDashboardSnapshotService.get_active(year, month)
        read_seconds = time.perf_counter() - read_started
        if not isinstance(verified, dict) or not verified:
            raise RuntimeError("dashboard snapshot warm-up completed but active payload is unavailable")
        app.logger.info(
            "dashboard_snapshot_acceptance status=PASS year=%s month=%s ims_upload_id=%s "
            "production_upload_id=%s read_seconds=%.4f",
            year, month, ims_id, production_id, read_seconds,
        )
        result["read_seconds"] = read_seconds
        return result
    except Exception:
        db.session.rollback()
        app.logger.exception("dashboard_snapshot_warm_failed year=%s month=%s", year, month)
        return {"status": "FAILED"}
    finally:
        db.session.remove()


def _warm_region_snapshots(app, year, month):
    """Build/retry the complete region generation and verify it is readable.

    Snapshot readiness is deliberately advisory after the IMS business import
    commits. A snapshot failure is reported to the user but never changes the
    completed IMS job back into a blocking/processing state.
    """
    started = time.monotonic()
    try:
        result = PersistentRegionSnapshotService.build_for_period(year, month)
        status = result.get("status")
        app.logger.info(
            "region_snapshot_warm status=%s year=%s month=%s regions=%s set_id=%s seconds=%.3f",
            status, year, month,
            result.get("regions", 0), result.get("set_id", 0),
            time.monotonic() - started,
        )
        if status not in {"ACTIVE", "REUSED"}:
            raise RuntimeError(f"region snapshot warm-up is not ready: status={status}")

        read_started = time.perf_counter()
        verified = PersistentRegionSnapshotService.get_active_all(year, month)
        read_seconds = time.perf_counter() - read_started
        expected_regions = int(result.get("regions") or 0)
        if not isinstance(verified, dict) or not verified:
            raise RuntimeError("region snapshot warm-up completed but active payload is unavailable")
        if expected_regions and len(verified) != expected_regions:
            raise RuntimeError(
                "region snapshot warm-up completed with incomplete active payload: "
                f"expected={expected_regions} actual={len(verified)}"
            )
        ims_id, production_id = PersistentRegionSnapshotService.source_identity(year, month)
        app.logger.info(
            "region_snapshot_acceptance status=PASS year=%s month=%s ims_upload_id=%s "
            "production_upload_id=%s regions=%s read_seconds=%.4f",
            year, month, ims_id, production_id, len(verified), read_seconds,
        )
        result["read_seconds"] = read_seconds
        return result
    except Exception:
        db.session.rollback()
        app.logger.exception("region_snapshot_warm_failed year=%s month=%s", year, month)
        return {"status": "FAILED"}
    finally:
        db.session.remove()


def _warm_representative_snapshots(app, year, month, *, force=False, job_id=None):
    """Prepare all representative pages before users navigate to them."""
    started = time.monotonic()
    recent_seconds = deque(maxlen=12)
    previous_tick = started
    try:
        def progress(done, total, name):
            nonlocal previous_tick
            now = time.monotonic()
            elapsed = max(now - started, 0.001)
            recent_seconds.append(max(now - previous_tick, 0.001))
            previous_tick = now
            remaining = max(total - done, 0)
            eta_seconds = (
                int(round(remaining * sum(recent_seconds) / len(recent_seconds)))
                if len(recent_seconds) >= 3 else None
            )
            if eta_seconds is None:
                eta_text = "süre hesaplanıyor"
            elif eta_seconds >= 60:
                eta_text = f"tahmini {max(1, round(eta_seconds / 60))} dk kaldı"
            else:
                eta_text = f"tahmini {eta_seconds} sn kaldı"

            if job_id is not None:
                value = 42 + round(52 * done / max(total, 1))
                IMSProgressStore.write(
                    job_id,
                    percent=min(value, 94),
                    stage="representative_snapshots",
                    message="IMS yüklemesi tamamlandı · snapshotlar hazırlanıyor",
                    detail=f"Temsilci snapshotları · {done}/{total} · {name} · {eta_text}",
                    status=IMSImportJob.STATUS_PROCESSING,
                )

            if done == 1 or done == total or done % 10 == 0:
                app.logger.info(
                    "representative_snapshot_warm_progress done=%s total=%s representative=%s "
                    "elapsed=%.3f rate_per_second=%.3f eta_seconds=%s",
                    done, total, name, elapsed, rate, eta_seconds,
                )

        result = PersistentRepresentativeSnapshotService.build_for_period(
            year, month, force=force, progress=progress
        )
        app.logger.info(
            "representative_snapshot_warm status=%s year=%s month=%s representatives=%s "
            "set_id=%s seconds=%.3f force=%s",
            result.get("status"), year, month,
            result.get("representatives", 0), result.get("set_id", 0),
            time.monotonic() - started, int(force),
        )
        return result
    except Exception:
        db.session.rollback()
        app.logger.exception(
            "representative_snapshot_warm_failed year=%s month=%s force=%s",
            year, month, int(force),
        )
        return {"status": "FAILED"}
    finally:
        db.session.remove()


def _backfill_latest_region_snapshots(app):
    """Preserve the region startup contract and warm representative snapshots too."""
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
        _warm_representative_snapshots(app, latest.year, latest.month)
    except Exception:
        db.session.rollback()
        app.logger.exception(
            "region_snapshot_startup_backfill_failed year=%s month=%s upload_id=%s",
            latest.year, latest.month, latest.id,
        )
    finally:
        db.session.remove()


def _snapshot_label(result):
    return "alındı" if result.get("status") in {"ACTIVE", "REUSED"} else "alınamadı"


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
                # Build the long representative generation first. Published pages
                # keep their previous immutable generation until every model is ready.
                IMSProgressStore.write(
                    job_id,
                    percent=42,
                    stage="representative_snapshots",
                    message="IMS yüklemesi tamamlandı · snapshotlar hazırlanıyor",
                    detail="Temsilci snapshotları hazırlanıyor",
                    status=IMSImportJob.STATUS_PROCESSING,
                )
                representative_result = _warm_representative_snapshots(
                    app, job_year, job_month, job_id=job_id
                )

                IMSProgressStore.write(
                    job_id,
                    percent=95,
                    stage="dashboard_snapshot",
                    message="IMS yüklemesi tamamlandı · snapshotlar hazırlanıyor",
                    detail="Temsilci snapshotları hazır · Dashboard snapshotı hazırlanıyor",
                    status=IMSImportJob.STATUS_PROCESSING,
                )
                dashboard_result = _warm_dashboard_snapshot(app, job_year, job_month)

                IMSProgressStore.write(
                    job_id,
                    percent=97,
                    stage="region_snapshots",
                    message="IMS yüklemesi tamamlandı · snapshotlar hazırlanıyor",
                    detail="Temsilci ve dashboard snapshotları hazır · Bölge snapshotları hazırlanıyor",
                    status=IMSImportJob.STATUS_PROCESSING,
                )
                region_result = _warm_region_snapshots(app, job_year, job_month)

                ready = (
                    dashboard_result.get("status") in {"ACTIVE", "REUSED"}
                    and region_result.get("status") in {"ACTIVE", "REUSED"}
                    and representative_result.get("status") in {"ACTIVE", "REUSED"}
                )
                snapshot_detail = (
                    f"Snapshot durumu · Dashboard: {_snapshot_label(dashboard_result)} · "
                    f"Bölge: {_snapshot_label(region_result)} · "
                    f"Temsilci: {_snapshot_label(representative_result)}"
                )
                if not ready:
                    completed.status = IMSImportJob.STATUS_FAILED
                    completed.error_message = "IMS işlendi ancak snapshot doğrulaması tamamlanamadığı için yayınlanmadı."
                    db.session.commit()
                else:
                    roster_result = IMSRosterSyncService.sync_latest()
                    app.logger.info("ims_roster_sync_success %s", roster_result)
                    IMSUploadLifecycleService.seal_snapshot_master_state(
                        upload_id=completed.ims_upload_id
                    )
                    summary = json.loads(completed.result_summary or "{}")
                    summary["publication_ready"] = True
                    completed.result_summary = json.dumps(summary, ensure_ascii=False)
                    db.session.commit()
                IMSProgressStore.write(
                    job_id,
                    percent=100,
                    stage="completed",
                    message=(
                        "IMS yüklemesi tamamlandı · snapshot alındı"
                        if ready
                        else "IMS yüklemesi tamamlandı · snapshotların bir kısmı alınamadı"
                    ),
                    detail=snapshot_detail,
                    status=IMSImportJob.STATUS_COMPLETED if ready else IMSImportJob.STATUS_FAILED,
                )
            db.session.remove()


if __name__ == "__main__":
    main()
