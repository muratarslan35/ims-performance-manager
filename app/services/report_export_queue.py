"""Filesystem-backed report export and prewarm queues.

No business rows are written. Jobs are small durable JSON markers consumed by a
separate low-priority report worker, so PDF/XLSX generation never occupies a
Gunicorn request worker.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from flask import current_app


class ReportExportQueue:
    STATUS_QUEUED = "QUEUED"
    STATUS_PROCESSING = "PROCESSING"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_FAILED = "FAILED"

    @classmethod
    def _root(cls) -> Path:
        configured = current_app.config.get("REPORT_EXPORT_QUEUE_FOLDER")
        root = Path(configured) if configured else Path(current_app.instance_path) / "report_export_queue"
        (root / "jobs").mkdir(parents=True, exist_ok=True)
        (root / "locks").mkdir(parents=True, exist_ok=True)
        (root / "warm").mkdir(parents=True, exist_ok=True)
        return root

    @classmethod
    def _job_path(cls, job_id: str) -> Path:
        return cls._root() / "jobs" / f"{job_id}.json"

    @classmethod
    def _queue_lock(cls) -> Path:
        return cls._root() / "locks" / "queue.lock"

    @classmethod
    def _atomic_write(cls, path: Path, payload: dict) -> None:
        tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)

    @classmethod
    def enqueue(
        cls,
        *,
        cache_key: str,
        file_type: str,
        filename: str,
        scope: str,
        scope_value: str,
        scope_values: list[str] | tuple[str, ...] | None = None,
        year: int,
        month: int,
        period: str,
        product_ids: list[int] | set[int] | tuple[int, ...],
    ) -> dict:
        if file_type not in {"pdf", "xlsx"}:
            raise ValueError("unsupported report export type")
        raw = f"{cache_key}|{file_type}"
        job_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
        path = cls._job_path(job_id)
        lock_path = cls._queue_lock()
        with lock_path.open("a+") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            existing = cls.read(job_id)
            if existing and existing.get("status") in {
                cls.STATUS_QUEUED,
                cls.STATUS_PROCESSING,
            }:
                return existing
            now = datetime.utcnow().isoformat()
            payload = {
                "job_id": job_id,
                "cache_key": cache_key,
                "file_type": file_type,
                "filename": filename,
                "scope": scope,
                "scope_value": scope_value or "",
                "scope_values": [
                    str(value) for value in (scope_values or ([scope_value] if scope_value else []))
                    if str(value or "").strip()
                ],
                "year": int(year),
                "month": int(month),
                "period": str(period),
                "product_ids": sorted(int(value) for value in product_ids),
                "status": cls.STATUS_QUEUED,
                "error": None,
                "created_at": now,
                "updated_at": now,
            }
            cls._atomic_write(path, payload)
            return payload

    @classmethod
    def read(cls, job_id: str) -> dict | None:
        path = cls._job_path(job_id)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    @classmethod
    def _jobs(cls) -> list[dict]:
        rows = []
        for path in cls._root().joinpath("jobs").glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            rows.append(payload)
        return sorted(rows, key=lambda row: (row.get("created_at") or "", row.get("job_id") or ""))

    @classmethod
    def position(cls, job_id: str) -> int | None:
        queued = [
            row for row in cls._jobs()
            if row.get("status") in {cls.STATUS_QUEUED, cls.STATUS_PROCESSING}
        ]
        for index, row in enumerate(queued, 1):
            if row.get("job_id") == job_id:
                return index
        return None

    @classmethod
    def claim_next(cls) -> dict | None:
        lock_path = cls._queue_lock()
        with lock_path.open("a+") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            for payload in cls._jobs():
                if payload.get("status") != cls.STATUS_QUEUED:
                    continue
                payload["status"] = cls.STATUS_PROCESSING
                payload["updated_at"] = datetime.utcnow().isoformat()
                cls._atomic_write(cls._job_path(payload["job_id"]), payload)
                return payload
        return None

    @classmethod
    def complete(cls, job: dict) -> None:
        payload = dict(job)
        payload["status"] = cls.STATUS_COMPLETED
        payload["error"] = None
        payload["updated_at"] = datetime.utcnow().isoformat()
        cls._atomic_write(cls._job_path(payload["job_id"]), payload)

    @classmethod
    def fail(cls, job: dict, error: str) -> None:
        payload = dict(job)
        payload["status"] = cls.STATUS_FAILED
        payload["error"] = str(error)[:1000]
        payload["updated_at"] = datetime.utcnow().isoformat()
        cls._atomic_write(cls._job_path(payload["job_id"]), payload)

    @classmethod
    def recover_stale(cls) -> int:
        recovered = 0
        lock_path = cls._queue_lock()
        with lock_path.open("a+") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            for payload in cls._jobs():
                if payload.get("status") != cls.STATUS_PROCESSING:
                    continue
                payload["status"] = cls.STATUS_QUEUED
                payload["updated_at"] = datetime.utcnow().isoformat()
                cls._atomic_write(cls._job_path(payload["job_id"]), payload)
                recovered += 1
        return recovered

    @classmethod
    def prune(cls, *, max_age_days: int = 45, max_jobs: int = 5000) -> int:
        cutoff = datetime.utcnow().timestamp() - max_age_days * 86400
        removed = 0
        paths = []
        for path in (cls._root() / "jobs").glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("status") not in {cls.STATUS_COMPLETED, cls.STATUS_FAILED}:
                    continue
                stat = path.stat()
                if stat.st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
                else:
                    paths.append(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        paths = sorted(paths, key=lambda path: path.stat().st_mtime, reverse=True)
        for path in paths[max_jobs:]:
            try:
                path.unlink(missing_ok=True)
                removed += 1
            except OSError:
                pass
        return removed


class ReportWarmQueue:
    @classmethod
    def _path(cls, year: int, month: int) -> Path:
        root = ReportExportQueue._root() / "warm"
        return root / f"{int(year):04d}-{int(month):02d}.json"

    @classmethod
    def enqueue(cls, year: int, month: int) -> dict:
        payload = {
            "year": int(year),
            "month": int(month),
            "status": "QUEUED",
            "scopes": None,
            "index": 0,
            "updated_at": datetime.utcnow().isoformat(),
        }
        ReportExportQueue._atomic_write(cls._path(year, month), payload)
        return payload

    @classmethod
    def claim_next(cls) -> dict | None:
        root = ReportExportQueue._root() / "warm"
        rows = []
        for path in root.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if payload.get("status") in {"QUEUED", "PROCESSING"}:
                rows.append((path, payload))
        if not rows:
            return None
        path, payload = sorted(rows, key=lambda item: item[0].name)[0]
        payload["status"] = "PROCESSING"
        payload["updated_at"] = datetime.utcnow().isoformat()
        ReportExportQueue._atomic_write(path, payload)
        return payload

    @classmethod
    def save(cls, payload: dict) -> None:
        payload = dict(payload)
        payload["updated_at"] = datetime.utcnow().isoformat()
        ReportExportQueue._atomic_write(
            cls._path(payload["year"], payload["month"]), payload
        )

    @classmethod
    def complete(cls, payload: dict) -> None:
        cls._path(payload["year"], payload["month"]).unlink(missing_ok=True)
