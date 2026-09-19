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
from app.services.representative_snapshot_refresh_queue import RepresentativeSnapshotRefreshQueue


# Import-mode activation marker: representative comparison snapshots now carry
# a versioned P2 > P1 > IMS monthly comparison contract. Import deploy restarts
# this worker so future IMS/production refresh queue events use the new builder.
# Activation revision: comparison-contract-v2.
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
            rate = done / elapsed
            remaining = max(total - done, 0)
            # ``done`` advances by a complete representative batch.  Treating
            # one callback interval as one representative made the displayed
            # ETA roughly one batch (normally 8x) too large.  The end-to-end
            # throughput already includes batch calculation and SQLite write
            # time, so it is the stable and truthful estimate here.
            eta_seconds = int(round(remaining / rate)) if done > 0 and rate > 0 else None
            if eta_seconds is None:
                eta_text = "süre hesaplanıyor"
            elif eta_seconds >= 60:
                eta_text = f"tahmini {max(1, round(eta_seconds / 60))} dk kaldı"
            else:
                eta_text = f"tahmini {eta_seconds} sn kaldı"

            if job_id is not None:
                value = 46 + round(48 * done / max(total, 1))
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
        representative_result = _warm_representative_snapshots(app, latest.year, latest.month)
        if representative_result.get("status") in {"ACTIVE", "REUSED"}:
            enrichment = PersistentRegionSnapshotService.enrich_for_period(
                latest.year, latest.month
            )
            app.logger.info(
                "region_snapshot_enrichment_startup status=%s year=%s month=%s regions=%s",
                enrichment.get("status"), latest.year, latest.month,
                enrichment.get("regions", 0),
            )
    except Exception:
        db.session.rollback()
        app.logger.exception(
            "region_snapshot_startup_backfill_failed year=%s month=%s upload_id=%s",
            latest.year, latest.month, latest.id,
        )
    finally:
        db.session.remove()


def _snapshot_label(result):
    return "alındı" if result.get("status") in {"ACTIVE", "REUSED", "ENRICHED"} else "alınamadı"


def _prepare_and_publish(app, completed):
    """Retryable read-model publication; the committed IMS always stays valid."""
    job_id, year, month = completed.id, completed.year, completed.month

    # Rollback safety is a business-import contract, not a snapshot-readiness
    # contract. Seal it before the long read-model warm-up so a region/rep
    # snapshot failure can never leave a valid IMS with a disabled rollback.
    if completed.ims_upload_id is None:
        raise RuntimeError("Completed IMS job has no upload id for rollback journal sealing.")
    if not IMSUploadLifecycleService.snapshot_master_state_sealed(
        upload_id=completed.ims_upload_id
    ):
        try:
            roster_result = IMSRosterSyncService.sync_latest()
            if int(roster_result.get("upload_id") or 0) != int(completed.ims_upload_id):
                raise RuntimeError(
                    "Rollback journal sealing refused because the completed job is not the active IMS."
                )
            app.logger.info("ims_roster_sync_success %s", roster_result)
            IMSUploadLifecycleService.ensure_snapshot_master_state_sealed(
                upload_id=completed.ims_upload_id
            )
            app.logger.info(
                "ims_rollback_master_journal_ready upload_id=%s job_id=%s",
                completed.ims_upload_id, job_id,
            )
        except Exception:
            db.session.rollback()
            refreshed = db.session.get(IMSImportJob, job_id)
            if refreshed is not None:
                refreshed.error_message = (
                    "IMS başarıyla işlendi; geri dönüş güvenlik günlüğü otomatik olarak yeniden denenecek."
                )
                db.session.commit()
            IMSProgressStore.write(
                job_id, percent=41, stage="snapshot_retry",
                message="IMS yüklendi · güvenlik günlüğü yeniden denenecek",
                detail="Geri dönüş güvenlik günlüğü tamamlanamadı; mevcut IMS verileri korunuyor.",
                status=IMSImportJob.STATUS_PROCESSING,
            )
            app.logger.exception(
                "ims_rollback_master_journal_failed upload_id=%s job_id=%s",
                completed.ims_upload_id, job_id,
            )
            return False

    IMSProgressStore.write(job_id, percent=42, stage="dashboard_snapshot",
        message="IMS yüklemesi tamamlandı · snapshotlar hazırlanıyor",
        detail="Dashboard snapshotı hazırlanıyor", status=IMSImportJob.STATUS_PROCESSING)
    dashboard_result = _warm_dashboard_snapshot(app, year, month)
    IMSProgressStore.write(job_id, percent=44, stage="region_snapshots",
        message="IMS yüklemesi tamamlandı · snapshotlar hazırlanıyor",
        detail="Dashboard hazır · Bölge snapshotları hazırlanıyor",
        status=IMSImportJob.STATUS_PROCESSING)
    region_result = _warm_region_snapshots(app, year, month)
    IMSProgressStore.write(job_id, percent=46, stage="representative_snapshots",
        message="IMS yüklemesi tamamlandı · snapshotlar hazırlanıyor",
        detail="Dashboard ve Bölge hazır · Temsilci snapshot paketleri hazırlanıyor",
        status=IMSImportJob.STATUS_PROCESSING)
    representative_result = _warm_representative_snapshots(app, year, month, job_id=job_id)
    enrichment_result = (
        PersistentRegionSnapshotService.enrich_for_period(year, month)
        if representative_result.get("status") in {"ACTIVE", "REUSED"}
        else {"status": "WAITING_REPRESENTATIVES"}
    )
    app.logger.info(
        "region_snapshot_enrichment status=%s year=%s month=%s regions=%s",
        enrichment_result.get("status"), year, month,
        enrichment_result.get("regions", 0),
    )
    ready = (
        dashboard_result.get("status") in {"ACTIVE", "REUSED"}
        and region_result.get("status") in {"ACTIVE", "REUSED"}
        and representative_result.get("status") in {"ACTIVE", "REUSED"}
        and enrichment_result.get("status") in {"ENRICHED", "REUSED"}
    )
    detail = (
        f"Snapshot durumu · Dashboard: {_snapshot_label(dashboard_result)} · "
        f"Bölge: {_snapshot_label(region_result)} · Temsilci: {_snapshot_label(representative_result)} · "
        f"Bölge görünümü: {_snapshot_label(enrichment_result)}"
    )
    if not ready:
        completed.error_message = "IMS başarıyla işlendi; eksik snapshotlar otomatik olarak yeniden denenecek."
        db.session.commit()
        IMSProgressStore.write(job_id, percent=98, stage="snapshot_retry",
            message="IMS yüklendi · snapshotlar yeniden denenecek", detail=detail,
            status=IMSImportJob.STATUS_PROCESSING)
        return False
    summary = json.loads(completed.result_summary or "{}")
    summary["publication_ready"] = True
    completed.result_summary = json.dumps(summary, ensure_ascii=False)
    completed.error_message = None
    db.session.commit()
    IMSProgressStore.write(job_id, percent=100, stage="completed",
        message="IMS yüklemesi tamamlandı · snapshot alındı", detail=detail,
        status=IMSImportJob.STATUS_COMPLETED)
    return True


def _retryable_publication_job():
    # Repair only the currently active IMS when an older deployment completed
    # the business import without sealing/publishing it. Never seal a historical
    # upload from today's master state.
    latest_upload = IMSRosterSyncService.latest_completed_upload()
    if latest_upload is not None:
        latest_job = (
            IMSImportJob.query
            .filter_by(
                ims_upload_id=latest_upload.id,
                status=IMSImportJob.STATUS_COMPLETED,
            )
            .order_by(desc(IMSImportJob.completed_at), desc(IMSImportJob.id))
            .first()
        )
        if latest_job is not None:
            try:
                summary = json.loads(latest_job.result_summary or "{}")
            except (TypeError, ValueError):
                summary = {}
            if (
                not IMSUploadLifecycleService.snapshot_master_state_sealed(
                    upload_id=latest_upload.id
                )
                or not summary.get("publication_ready")
            ):
                return latest_job

    for job in IMSImportJob.query.filter_by(status=IMSImportJob.STATUS_COMPLETED).order_by(
        desc(IMSImportJob.completed_at), desc(IMSImportJob.id)
    ).limit(5):
        stored = IMSProgressStore.read(job.id) or {}
        if stored.get("stage") == "snapshot_retry":
            return job
    return None


def _process_representative_refresh_queue(app):
    """Run one durable production-triggered refresh behind IMS publication work."""
    item = RepresentativeSnapshotRefreshQueue.next()
    if item is None:
        return False

    year = int(item.get("year"))
    month = int(item.get("month"))
    reason = str(item.get("reason") or "production")
    latest = IMSUpload.query.filter_by(
        year=year, month=month, status=IMSUpload.STATUS_COMPLETED
    ).order_by(
        desc(IMSUpload.week_number), desc(IMSUpload.completed_at), desc(IMSUpload.id)
    ).first()
    if latest is None:
        # A successor month may have disappeared through an intentional rollback.
        # There is nothing to refresh; its first future snapshot will use the
        # then-current P2 > P1 > IMS sources.
        RepresentativeSnapshotRefreshQueue.complete(item)
        app.logger.info(
            "representative_refresh_queue_skipped year=%s month=%s reason=no_completed_ims",
            year, month,
        )
        return True

    result = _warm_representative_snapshots(app, year, month, force=True)
    if result.get("status") in {"ACTIVE", "REUSED"}:
        RepresentativeSnapshotRefreshQueue.complete(item)
        app.logger.info(
            "representative_refresh_queue_completed year=%s month=%s reason=%s set_id=%s",
            year, month, reason, result.get("set_id", 0),
        )
    else:
        # Keep the marker durable. The worker will retry after any currently
        # BUILDING generation finishes; no running IMS/snapshot work is stopped.
        app.logger.warning(
            "representative_refresh_queue_deferred year=%s month=%s reason=%s status=%s",
            year, month, reason, result.get("status"),
        )
    db.session.remove()
    return True


def main():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    app = create_app()
    with app.app_context():
        IMSImportQueue.recover_stale()
        _backfill_latest_region_snapshots(app)
        next_publication_retry = 0.0
        while not stopping:
            job = IMSImportQueue.claim_next()
            if job is None:
                if time.monotonic() >= next_publication_retry:
                    retry_job = _retryable_publication_job()
                    if retry_job is not None:
                        _prepare_and_publish(app, retry_job)
                    next_publication_retry = time.monotonic() + 60
                # Production-result refreshes are deliberately lower priority
                # than IMS imports/publication. Once started they finish
                # atomically; newly queued IMS work waits for the next loop.
                if _process_representative_refresh_queue(app):
                    db.session.remove()
                    continue
                db.session.remove()
                time.sleep(2)
                continue
            job_id = job.id
            job_year = job.year
            job_month = job.month
            IMSImportQueue.process(job)
            completed = db.session.get(IMSImportJob, job_id)
            if completed is not None and completed.status == IMSImportJob.STATUS_COMPLETED:
                _prepare_and_publish(app, completed)
            db.session.remove()


if __name__ == "__main__":
    main()
