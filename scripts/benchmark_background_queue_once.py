"""One-shot production-host benchmark for the real background IMS queue path.

This script is intentionally safe for the live host:
- DATABASE_URL must point to an isolated /tmp SQLite copy.
- The live database is never mutated.
- A retained 7.Hafta workbook is copied to a temporary queue staging file.
- IMSImportQueue.process() is exercised exactly as the production worker does.
- The temporary staging file and isolated DB are removed by the caller/workflow.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app import create_app
from app.extensions import db
from app.models import CompetitionData, IMSFact, IMSImportJob, IMSRawData, IMSSummary, IMSUpload, Target
from app.services.import_result_report import latest_import_report
from app.services.ims_import_queue import IMSImportQueue
from app.services.ims_import_service import IMSImportService
from config import Config


class QueueBenchmarkConfig(Config):
    TESTING = True
    USER_VAULT_PATH = Path("/tmp/ims-queue-benchmark-users-disabled.db")


def _emit(kind: str, **payload) -> None:
    print(
        "IMS_QUEUE_BENCHMARK_" + kind + "|" + json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
        flush=True,
    )


def _proc_memory() -> dict[str, int | None]:
    result = {"rss_bytes": None, "peak_rss_bytes": None}
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    result["rss_bytes"] = int(line.split()[1]) * 1024
                elif line.startswith("VmHWM:"):
                    result["peak_rss_bytes"] = int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return result


def _source_candidate(upload_folder: Path) -> tuple[Path, str]:
    # Prefer retained upload evidence whose human filename explicitly carries
    # the week identity. This keeps the benchmark semantic and avoids relying
    # on a hard-coded server path.
    uploads = IMSUpload.query.order_by(IMSUpload.uploaded_at.desc(), IMSUpload.id.desc()).all()
    for upload in uploads:
        if IMSImportService.extract_week_number(upload.file_name) != 7:
            continue
        direct = upload_folder / upload.file_name
        if direct.is_file():
            return direct, upload.file_name

    # Historical synchronous imports can survive without a matching current DB
    # row. Search only the IMS upload tree, excluding production-result and queue
    # staging directories, and require the filename itself to resolve to week 7.
    candidates = []
    for path in upload_folder.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".xlsx", ".xls"}:
            continue
        parts = {part.casefold() for part in path.parts}
        if "production_results" in parts or "ims_queue" in parts:
            continue
        if IMSImportService.extract_week_number(path.name) == 7:
            candidates.append(path)
    if candidates:
        candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        return candidates[0], candidates[0].name

    sample = sorted(
        str(path.relative_to(upload_folder))
        for path in upload_folder.rglob("*")
        if path.is_file() and path.suffix.lower() in {".xlsx", ".xls"}
    )[:30]
    _emit("SOURCE_MISSING", upload_folder=str(upload_folder), workbook_sample=sample)
    raise FileNotFoundError("Sunucuda 7.Hafta kimliği taşıyan retained IMS workbooku bulunamadı.")


def main() -> int:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith("sqlite:///"):
        raise RuntimeError("Benchmark yalnız izole SQLite kopyasında çalışabilir.")
    database_path = Path(database_url.removeprefix("sqlite:///"))
    if not database_path.name.startswith("ims-queue-benchmark-"):
        raise RuntimeError(f"Güvensiz benchmark DB yolu: {database_path}")
    if database_path.resolve() == Path("instance/ipm.db").resolve():
        raise RuntimeError("Canlı DB üzerinde queue benchmark engellendi.")

    app = create_app(QueueBenchmarkConfig)
    with app.app_context():
        upload_folder = Path(app.config["UPLOAD_FOLDER"])
        source, original_name = _source_candidate(upload_folder)
        week_number = IMSImportService.extract_week_number(original_name)
        if week_number != 7:
            raise AssertionError(f"Kaynak hafta kimliği beklenmeyen değer: {week_number}")

        staging_folder = upload_folder / "ims_queue"
        staging_folder.mkdir(parents=True, exist_ok=True)
        stored_name = f"queue-benchmark-{uuid4().hex}{source.suffix.lower()}"
        staging_path = staging_folder / stored_name
        shutil.copy2(source, staging_path)

        digest = hashlib.sha256()
        with staging_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)

        before_feb_raw = IMSRawData.query.filter_by(year=2026, month=2).count()
        before_upload_ids = {item[0] for item in db.session.query(IMSUpload.id).all()}
        started_at = datetime.utcnow()
        job = IMSImportJob(
            status=IMSImportJob.STATUS_PROCESSING,
            file_name=original_name,
            stored_file_name=stored_name,
            source_hash=digest.hexdigest(),
            year=2026,
            month=2,
            clear_before_import=True,
            uploaded_by="ISOLATED_QUEUE_BENCHMARK",
            started_at=started_at,
            heartbeat_at=started_at,
        )
        db.session.add(job)
        db.session.commit()
        job_id = job.id

        _emit(
            "START",
            database=str(database_path),
            source=str(source),
            original_name=original_name,
            detected_week_number=week_number,
            before_feb_raw=before_feb_raw,
            **_proc_memory(),
        )
        wall_started = time.monotonic()
        IMSImportQueue.process(job)
        wall_seconds = time.monotonic() - wall_started

        job = db.session.get(IMSImportJob, job_id)
        if job is None:
            raise AssertionError("Benchmark queue job kaydı kayboldu.")
        if job.status != IMSImportJob.STATUS_COMPLETED:
            raise AssertionError(f"Queue benchmark tamamlanmadı: status={job.status}, error={job.error_message}")
        if not job.ims_upload_id or job.ims_upload_id in before_upload_ids:
            raise AssertionError(f"Yeni IMS upload oluşmadı: {job.ims_upload_id}")

        upload = db.session.get(IMSUpload, job.ims_upload_id)
        stats = json.loads(job.result_summary or "{}")
        stage_telemetry = stats.get("stage_telemetry") or {}
        report = latest_import_report(upload_id=upload.id)
        critical = (report or {}).get("critical") or {}
        after_feb_raw = IMSRawData.query.filter_by(year=2026, month=2).count()
        counts = {
            "competition": CompetitionData.query.filter_by(upload_id=upload.id).count(),
            "fact": IMSFact.query.filter_by(upload_id=upload.id).count(),
            "raw": IMSRawData.query.filter_by(upload_id=upload.id).count(),
            "summary": IMSSummary.query.filter_by(year=2026, month=2).count(),
            "target": Target.query.filter_by(year=2026, month=2).count(),
        }
        result = {
            "result": "PASS",
            "job_id": job.id,
            "upload_id": upload.id,
            "file_name": upload.file_name,
            "week_number": upload.week_number,
            "detected_week_number": stats.get("detected_week_number"),
            "wall_seconds": round(wall_seconds, 4),
            "background_job_seconds": stats.get("background_job_seconds"),
            "processing_seconds": upload.processing_time,
            "competition_bulk_chunk_size": stats.get("competition_bulk_chunk_size"),
            "competition_compiled_fast_path": stats.get("competition_compiled_fast_path"),
            "source": upload.source_record_count,
            "stored": upload.stored_source_record_count,
            "reconciliation": upload.reconciliation_status,
            "counts": counts,
            "before_feb_raw": before_feb_raw,
            "after_feb_raw": after_feb_raw,
            "feb_raw_delta": after_feb_raw - before_feb_raw,
            "critical": critical,
            "final_result": (report or {}).get("final_result"),
            "stage_telemetry": stage_telemetry,
            **_proc_memory(),
        }
        print("IMS_QUEUE_BENCHMARK|" + json.dumps(result, ensure_ascii=False, sort_keys=True, default=str), flush=True)

        if upload.week_number != 7 or stats.get("detected_week_number") != 7:
            raise AssertionError(f"7.Hafta queue kimliği korunmadı: {result}")
        if upload.file_name != original_name:
            raise AssertionError(f"Orijinal dosya adı korunmadı: {upload.file_name!r} != {original_name!r}")
        if upload.source_record_count != 24816 or upload.stored_source_record_count != 24816:
            raise AssertionError(f"source/stored golden uyuşmuyor: {upload.source_record_count}/{upload.stored_source_record_count}")
        if upload.reconciliation_status != "PASSED":
            raise AssertionError(f"reconciliation={upload.reconciliation_status}")
        if report is None or report.get("final_result") != "PASS" or any(int(value or 0) for value in critical.values()):
            raise AssertionError(f"Import audit gate başarısız: report={report}")
        if counts != {"competition": 467320, "fact": 3426, "raw": 25104, "summary": 888, "target": 1211}:
            raise AssertionError(f"Golden counts değişti: {counts}")
        # A UUID-staged weekly file must append its week evidence; destructive
        # monthly clear would collapse this delta instead of preserving history.
        if after_feb_raw - before_feb_raw < 24000:
            raise AssertionError(
                f"Haftalık import aylık clear davranışına düşmüş olabilir: before={before_feb_raw}, after={after_feb_raw}"
            )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
