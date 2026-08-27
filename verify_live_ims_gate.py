"""Fast read-only production IMS integrity gate.

This gate validates the latest completed IMS upload without re-importing the
workbook. The expensive full workbook acceptance remains available separately
for explicit/manual importer qualification.
"""
from __future__ import annotations

import json
import time

from sqlalchemy import func

from app import create_app
from app.extensions import db
from app.models import (
    CompetitionData,
    IMSFact,
    IMSImportJob,
    IMSRawData,
    IMSSummary,
    IMSUpload,
    Target,
)
from app.services.import_result_report import latest_import_report
from config import Config


class GateConfig(Config):
    TESTING = True


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _latest_job_telemetry(upload):
    """Return bounded read-only timing evidence for the latest completed import.

    The background queue already persists the importer's stage telemetry in
    ``result_summary``. Surface it in deployment evidence so a slow production
    import can be diagnosed without restarting the worker, re-reading the
    workbook, or mutating live data.
    """
    job = (
        IMSImportJob.query.filter_by(ims_upload_id=upload.id)
        .order_by(IMSImportJob.completed_at.desc(), IMSImportJob.id.desc())
        .first()
    )
    result_summary = {}
    if job is not None and job.result_summary:
        try:
            result_summary = json.loads(job.result_summary)
        except (TypeError, ValueError, json.JSONDecodeError):
            result_summary = {}

    period_filter = (
        CompetitionData.year == upload.year,
        CompetitionData.month == upload.month,
    )
    period_rows = db.session.query(func.count(CompetitionData.id)).filter(*period_filter).scalar() or 0
    period_partitions = (
        db.session.query(func.count(func.distinct(CompetitionData.upload_id)))
        .filter(*period_filter)
        .scalar()
        or 0
    )

    queue_wait_seconds = None
    job_seconds = result_summary.get("background_job_seconds")
    if job is not None and job.queued_at is not None and job.started_at is not None:
        queue_wait_seconds = round((job.started_at - job.queued_at).total_seconds(), 3)
    if job_seconds is None and job is not None and job.started_at is not None and job.completed_at is not None:
        job_seconds = round((job.completed_at - job.started_at).total_seconds(), 3)

    return {
        "job_id": job.id if job is not None else None,
        "job_status": job.status if job is not None else None,
        "queue_wait_seconds": queue_wait_seconds,
        "background_job_seconds": job_seconds,
        "importer_processing_seconds": float(upload.processing_time or 0.0),
        "stage_telemetry": result_summary.get("stage_telemetry") or {},
        "competition_compiled_fast_path": result_summary.get("competition_compiled_fast_path"),
        "competition_bulk_chunk_size": result_summary.get("competition_bulk_chunk_size"),
        "competition_period_rows": int(period_rows),
        "competition_period_upload_partitions": int(period_partitions),
        "latest_upload_competition_rows": CompetitionData.query.filter_by(upload_id=upload.id).count(),
    }


def main():
    started = time.monotonic()
    app = create_app(GateConfig)
    with app.app_context():
        upload = (
            IMSUpload.query.filter_by(status="COMPLETED")
            .order_by(IMSUpload.completed_at.desc(), IMSUpload.id.desc())
            .first()
        )
        _require(upload is not None, "COMPLETED IMS upload bulunamadı.")
        _require(upload.reconciliation_status == "PASSED", f"reconciliation={upload.reconciliation_status}")
        _require(int(upload.source_record_count or 0) > 0, "source_record_count sıfır.")
        _require(
            int(upload.source_record_count or 0) == int(upload.stored_source_record_count or 0),
            f"source/stored uyuşmuyor: {upload.source_record_count}/{upload.stored_source_record_count}",
        )
        _require(int(upload.invalid_metric_count or 0) == 0, f"invalid_metric={upload.invalid_metric_count}")

        report = latest_import_report(upload_id=upload.id)
        _require(report is not None, f"Import audit raporu yok: upload={upload.id}")
        _require(report.get("final_result") == "PASS", f"import report FAIL: {report.get('final_result')}")
        critical = report.get("critical") or {}
        _require(not any(int(value or 0) for value in critical.values()), f"blocking counters={critical}")
        sheets = report.get("sheets") or {}
        _require(int(sheets.get("verified", 0)) == int(sheets.get("total", 0)), f"sheet coverage={sheets}")
        source = report.get("source") or {}
        _require(
            int(source.get("records", 0)) == int(source.get("stored", 0)) == int(upload.source_record_count or 0),
            f"audit source/stored={source}, upload={upload.source_record_count}/{upload.stored_source_record_count}",
        )

        actual_counts = {
            "facts": IMSFact.query.filter_by(upload_id=upload.id).count(),
            "summary": IMSSummary.query.filter_by(year=upload.year, month=upload.month).count(),
            "targets": Target.query.filter_by(year=upload.year, month=upload.month).count(),
            "competition": CompetitionData.query.filter_by(upload_id=upload.id).count(),
            "raw": IMSRawData.query.filter_by(upload_id=upload.id).count(),
            "official_brick_spread": IMSRawData.query.filter_by(
                upload_id=upload.id, sheet_type="official_brick_spread_master"
            ).count(),
            "official_aggregates": IMSRawData.query.filter(
                IMSRawData.upload_id == upload.id,
                IMSRawData.sheet_type.in_(("official_target_aggregate", "official_actual_aggregate")),
            ).count(),
        }
        expected_counts = report.get("counts") or {}
        for key in ("facts", "summary", "targets", "competition"):
            expected = int(expected_counts.get(key, 0) or 0)
            _require(expected > 0, f"audit {key}=0")
            _require(actual_counts[key] == expected, f"{key} count mismatch: db={actual_counts[key]} audit={expected}")

        # raw_record_count is the importer semantic/raw metric counter, not the
        # physical ims_raw_data row count. The table also stores side-channel
        # rows such as official aggregate and Brick Spread masters. Therefore a
        # healthy upload can legitimately have physical RAW > raw_record_count
        # (week 7: 25,104 vs 24,816). Guard against loss instead of treating the
        # additional validated side-channel rows as corruption.
        semantic_raw = int(upload.raw_record_count or 0)
        _require(semantic_raw > 0, "raw_record_count sıfır.")
        _require(
            actual_counts["raw"] >= semantic_raw,
            f"physical raw eksik: db={actual_counts['raw']} semantic={semantic_raw}",
        )
        for key in ("official_brick_spread", "official_aggregates"):
            if key in expected_counts:
                expected = int(expected_counts.get(key, 0) or 0)
                _require(
                    actual_counts[key] == expected,
                    f"{key} count mismatch: db={actual_counts[key]} audit={expected}",
                )

        _require(actual_counts["facts"] == int(upload.fact_record_count or 0), f"fact mismatch: db={actual_counts['facts']} upload={upload.fact_record_count}")

        national = report.get("national_region")
        if national:
            _require(bool(national.get("passed")), f"national_region failed: {national}")
            _require(not national.get("conflicts"), f"national_region conflicts: {national.get('conflicts')}")

        payload = {
            "result": "PASS",
            "seconds": round(time.monotonic() - started, 4),
            "upload_id": upload.id,
            "file_name": upload.file_name,
            "period": [upload.year, upload.month, upload.week_number],
            "source": int(upload.source_record_count or 0),
            "stored": int(upload.stored_source_record_count or 0),
            "semantic_raw": semantic_raw,
            "physical_raw": actual_counts["raw"],
            "raw_side_channel_delta": actual_counts["raw"] - semantic_raw,
            "reconciliation": upload.reconciliation_status,
            "critical": critical,
            "sheets": sheets,
            "counts": actual_counts,
        }
        print("IMS_LIVE_GATE|" + json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
        telemetry = _latest_job_telemetry(upload)
        print("IMS_IMPORT_TELEMETRY|" + json.dumps(telemetry, ensure_ascii=False, sort_keys=True, default=str))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
