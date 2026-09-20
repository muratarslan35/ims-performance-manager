"""Low-priority report export/cache worker.

The web tier only reads cached report JSON and enqueues expensive PDF/XLSX
generation. This worker serializes those CPU/memory-heavy operations and yields
entirely while IMS import/publication work is active.
"""

from __future__ import annotations

import signal
import time

from app import create_app
from app.extensions import db
from app.models import IMSImportJob
from app.services.executive_reporting_service import ExecutiveReportingService
from app.services.report_cache_service import ReportCacheService
from app.services.report_export_queue import ReportExportQueue, ReportWarmQueue


stopping = False


def _stop(*_args):
    global stopping
    stopping = True


def _ims_busy() -> bool:
    try:
        return (
            IMSImportJob.query.filter(
                IMSImportJob.status.in_(
                    (IMSImportJob.STATUS_QUEUED, IMSImportJob.STATUS_PROCESSING)
                )
            ).count()
            > 0
        )
    finally:
        # A long-lived report worker must never pin a SQLite read transaction
        # and prevent WAL checkpoints while it is idle.
        db.session.remove()


def _process_export(app) -> bool:
    job = ReportExportQueue.claim_next()
    if job is None:
        return False

    try:
        cached = ReportCacheService.cached_export(job["cache_key"], job["file_type"])
        if cached is None:
            report = ReportCacheService.read_by_key(job["cache_key"])
            if not report:
                raise RuntimeError("Rapor read-model cache'i bulunamadı.")

            service = ExecutiveReportingService(
                year=int(report["year"]),
                month=int(report["month"]),
                period=str(report["period"]),
                scope=str(report["scope"]),
                scope_value="",
                product_ids=[],
            )
            output = (
                service.to_excel(report)
                if job["file_type"] == "xlsx"
                else service.to_pdf(report)
            )
            ReportCacheService.write_export(
                job["cache_key"], job["file_type"], output.getvalue()
            )

        ReportExportQueue.complete(job)
        app.logger.info(
            "report_export_completed job_id=%s cache_key=%s type=%s",
            job["job_id"],
            job["cache_key"],
            job["file_type"],
        )
    except Exception as exc:
        ReportExportQueue.fail(job, str(exc))
        app.logger.exception(
            "report_export_failed job_id=%s cache_key=%s type=%s",
            job.get("job_id"),
            job.get("cache_key"),
            job.get("file_type"),
        )
    finally:
        db.session.remove()
    return True


def _warm_scopes(year: int, month: int) -> list[dict]:
    service = ExecutiveReportingService(
        year=year, month=month, period="monthly", scope="national"
    )
    options = service.filter_options()
    scopes = [{"scope": "national", "scope_value": ""}]
    scopes.extend(
        {"scope": "region", "scope_value": str(item["value"])}
        for item in options["regions"]
    )
    scopes.extend(
        {"scope": "city", "scope_value": str(item["value"])}
        for item in options["cities"]
    )
    scopes.extend(
        {"scope": "representative", "scope_value": str(item.id)}
        for item in options["representatives"]
    )
    return scopes


def _process_warm(app) -> bool:
    item = ReportWarmQueue.claim_next()
    if item is None:
        return False

    try:
        if item.get("scopes") is None:
            item["scopes"] = _warm_scopes(int(item["year"]), int(item["month"]))
            item["index"] = 0
            ReportWarmQueue.save(item)

        index = int(item.get("index") or 0)
        scopes = item.get("scopes") or []
        if index >= len(scopes):
            ReportWarmQueue.complete(item)
            return True

        spec = scopes[index]
        service = ExecutiveReportingService(
            year=int(item["year"]),
            month=int(item["month"]),
            period="monthly",
            scope=str(spec["scope"]),
            scope_value=str(spec.get("scope_value") or ""),
            product_ids=[],
        )
        _report, cache_key, built = ReportCacheService.get_or_build(service)
        app.logger.info(
            "report_cache_warm scope=%s scope_value=%s year=%s month=%s "
            "cache_key=%s built=%s progress=%s/%s",
            spec["scope"],
            spec.get("scope_value") or "",
            item["year"],
            item["month"],
            cache_key,
            int(built),
            index + 1,
            len(scopes),
        )
        item["index"] = index + 1
        if item["index"] >= len(scopes):
            ReportWarmQueue.complete(item)
        else:
            ReportWarmQueue.save(item)
    except Exception:
        app.logger.exception(
            "report_cache_warm_failed year=%s month=%s index=%s",
            item.get("year"),
            item.get("month"),
            item.get("index"),
        )
        # Keep the durable marker for a later retry, but do not hot-loop.
        item["status"] = "QUEUED"
        ReportWarmQueue.save(item)
        time.sleep(2)
    finally:
        db.session.remove()
    return True


def main():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    app = create_app()

    with app.app_context():
        recovered = ReportExportQueue.recover_stale()
        if recovered:
            app.logger.warning("report_export_recovered_stale count=%s", recovered)

        next_prune = 0.0
        while not stopping:
            if _ims_busy():
                # IMS import/publication is the highest-priority workload.
                time.sleep(2)
                continue

            # User-triggered exports always outrank speculative prewarming.
            if _process_export(app):
                time.sleep(0.05)
                continue
            if _process_warm(app):
                time.sleep(0.10)
                continue

            if time.monotonic() >= next_prune:
                result = ReportCacheService.prune()
                if result["removed"]:
                    app.logger.info("report_cache_prune removed=%s", result["removed"])
                next_prune = time.monotonic() + 3600

            time.sleep(1)


if __name__ == "__main__":
    main()
