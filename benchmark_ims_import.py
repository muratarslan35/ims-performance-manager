"""Benchmark the latest failed IMS workbook on an isolated SQLite copy.

Safety contract:
- DATABASE_URL must point to /tmp/ims-benchmark-*.db.
- The live production database is never mutated.
- The workbook is selected semantically from IMSUpload metadata; no workbook name,
  sheet name, header row, or column position is hardcoded.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from app import create_app
from app.extensions import db
from app.models import CompetitionData, IMSFact, IMSRawData, IMSSummary, IMSUpload, Target
from app.services.ims_import_service import IMSImportService
from config import Config


BLOCKING_STATS = (
    "unclassified_sheet",
    "unclassified_master_cell",
    "unresolved_representative",
    "unresolved_product",
    "invalid_metric",
    "row_error",
    "conflicting_match",
    "duplicate_conflict",
)


class BenchmarkConfig(Config):
    TESTING = True
    USER_VAULT_PATH = Path("/tmp/ims-benchmark-users-disabled.db")


def _source_path(app, upload: IMSUpload) -> Path:
    upload_folder = Path(app.config["UPLOAD_FOLDER"])
    direct = upload_folder / upload.file_name
    if direct.is_file():
        return direct
    normalized = upload.file_name.casefold()
    matches = [
        path for path in upload_folder.glob("*")
        if path.is_file() and path.name.casefold() == normalized
    ]
    if len(matches) == 1:
        return matches[0]
    raise FileNotFoundError(
        f"Benchmark workbook bulunamadı: upload_id={upload.id}, "
        f"file={upload.file_name}, folder={upload_folder}"
    )


def _select_upload() -> IMSUpload:
    requested_id = os.environ.get("IMS_BENCHMARK_UPLOAD_ID")
    if requested_id:
        upload = db.session.get(IMSUpload, int(requested_id))
        if upload is None:
            raise RuntimeError(f"IMS_BENCHMARK_UPLOAD_ID bulunamadı: {requested_id}")
        return upload

    candidates = (
        IMSUpload.query
        .filter(IMSUpload.status != "COMPLETED")
        .order_by(IMSUpload.uploaded_at.desc(), IMSUpload.id.desc())
        .all()
    )
    for upload in candidates:
        try:
            _source_path(create_app(BenchmarkConfig), upload)
            return upload
        except FileNotFoundError:
            continue
    raise RuntimeError("Sunucuda benchmark edilebilir başarısız IMS workbooku bulunamadı.")


def main() -> int:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith("sqlite:///"):
        raise RuntimeError("Benchmark yalnız izole SQLite kopyası üzerinde çalıştırılabilir.")
    db_path = Path(database_url.removeprefix("sqlite:///"))
    if not db_path.name.startswith("ims-benchmark-") or db_path.resolve() == Path("instance/ipm.db").resolve():
        raise RuntimeError(f"Canlı DB üzerinde benchmark engellendi: {db_path}")

    app = create_app(BenchmarkConfig)
    with app.app_context():
        requested_id = os.environ.get("IMS_BENCHMARK_UPLOAD_ID")
        if requested_id:
            source_upload = db.session.get(IMSUpload, int(requested_id))
            if source_upload is None:
                raise RuntimeError(f"IMS_BENCHMARK_UPLOAD_ID bulunamadı: {requested_id}")
        else:
            candidates = (
                IMSUpload.query
                .filter(IMSUpload.status != "COMPLETED")
                .order_by(IMSUpload.uploaded_at.desc(), IMSUpload.id.desc())
                .all()
            )
            source_upload = next(
                (upload for upload in candidates if (Path(app.config["UPLOAD_FOLDER"]) / upload.file_name).is_file()),
                None,
            )
            if source_upload is None:
                raise RuntimeError("Sunucuda benchmark edilebilir başarısız IMS workbooku bulunamadı.")

        source = _source_path(app, source_upload)
        before_ids = {row[0] for row in db.session.query(IMSUpload.id).all()}

        started = time.monotonic()
        result = IMSImportService(str(source), uploaded_by="SERVER_BENCHMARK").run(
            source_upload.year,
            source_upload.month,
            clear_before_import=False,
            week_number=source_upload.week_number,
        )
        wall_seconds = time.monotonic() - started

        stats = result.get("statistics") or {}
        stages = stats.get("stage_telemetry") or {}
        stage_seconds = sum(float(item.get("duration_seconds") or 0) for item in stages.values())
        unexplained_seconds = max(0.0, wall_seconds - stage_seconds)
        blocking = {key: int(stats.get(key, 0) or 0) for key in BLOCKING_STATS}

        new_upload_id = result.get("upload_id")
        new_upload = db.session.get(IMSUpload, int(new_upload_id)) if new_upload_id else None
        if new_upload is None or new_upload.id in before_ids:
            raise AssertionError("Benchmark yeni izole upload kaydı üretemedi.")

        counts = {
            "fact": IMSFact.query.filter_by(upload_id=new_upload.id).count(),
            "raw": IMSRawData.query.filter_by(upload_id=new_upload.id).count(),
            "competition": CompetitionData.query.filter_by(upload_id=new_upload.id).count(),
            "summary": IMSSummary.query.filter_by(year=new_upload.year, month=new_upload.month).count(),
            "target": Target.query.filter_by(year=new_upload.year, month=new_upload.month).count(),
        }
        peak_rss = max(
            (int(item.get("peak_rss_bytes_after") or 0) for item in stages.values()),
            default=0,
        ) or None

        report = {
            "result": "PASS" if result.get("success") and result.get("final_result") == "PASS" else "FAIL",
            "source_upload": {
                "id": source_upload.id,
                "file_name": source_upload.file_name,
                "status": source_upload.status,
                "year": source_upload.year,
                "month": source_upload.month,
                "week_number": source_upload.week_number,
                "sheet_count": source_upload.sheet_count,
            },
            "benchmark_upload_id": new_upload.id,
            "wall_seconds": round(wall_seconds, 4),
            "processing_seconds": result.get("processing_time"),
            "instrumented_stage_seconds": round(stage_seconds, 4),
            "unattributed_seconds": round(unexplained_seconds, 4),
            "peak_rss_bytes": peak_rss,
            "stages": stages,
            "blocking": blocking,
            "counts": counts,
            "source_record_count": new_upload.source_record_count,
            "stored_source_record_count": new_upload.stored_source_record_count,
            "reconciliation_status": new_upload.reconciliation_status,
            "errors": result.get("errors") or [],
        }
        print("IMS_SERVER_BENCHMARK|" + json.dumps(report, ensure_ascii=False, sort_keys=True, default=str))

        if report["result"] != "PASS":
            raise AssertionError(f"IMS benchmark import FAIL: {report['errors']}")
        if any(blocking.values()):
            raise AssertionError(f"Benchmark blocking counters sıfır değil: {blocking}")
        if new_upload.source_record_count != new_upload.stored_source_record_count:
            raise AssertionError(
                "Benchmark source/stored uyuşmuyor: "
                f"{new_upload.source_record_count}/{new_upload.stored_source_record_count}"
            )
        if new_upload.reconciliation_status != "PASSED":
            raise AssertionError(f"Benchmark reconciliation PASS değil: {new_upload.reconciliation_status}")
        if counts["fact"] <= 0:
            raise AssertionError("Benchmark FACT üretmedi.")
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("IMS_SERVER_BENCHMARK|" + json.dumps({"result": "FAIL", "error": str(exc)}, ensure_ascii=False))
        raise
