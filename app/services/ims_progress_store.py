"""Small persistent progress channel for long-running IMS imports.

Progress is deliberately stored outside the main IMS SQLite transaction. The
import remains atomic while the browser can still observe committed progress
from a different request/process. Post-import read-model warm-up deliberately
uses the same channel so 100% means both business data and analysis screens are
ready, not merely that the workbook transaction committed.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import current_app


class IMSProgressStore:
    """Atomic JSON progress records keyed by queue job id."""

    POST_IMPORT_STAGES = {
        "read_models",
        "dashboard_snapshot",
        "representative_snapshots",
    }

    @classmethod
    def _folder(cls) -> Path:
        folder = Path(current_app.instance_path) / "ims_progress"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    @classmethod
    def _path(cls, job_id: int) -> Path:
        return cls._folder() / f"job-{int(job_id)}.json"

    @classmethod
    def write(
        cls,
        job_id: int,
        *,
        percent: int,
        stage: str,
        message: str,
        detail: str | None = None,
        status: str = "PROCESSING",
    ) -> dict[str, Any]:
        payload = {
            "job_id": int(job_id),
            "percent": max(0, min(int(percent), 100)),
            "stage": str(stage or ""),
            "message": str(message or ""),
            "detail": str(detail) if detail else None,
            "status": str(status or "PROCESSING"),
            "updated_at": datetime.utcnow().isoformat(),
        }
        path = cls._path(job_id)
        temp = path.with_suffix(f".tmp-{os.getpid()}")
        temp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(temp, path)
        return payload

    @classmethod
    def read(cls, job_id: int) -> dict[str, Any] | None:
        path = cls._path(job_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        try:
            data["percent"] = max(0, min(int(data.get("percent", 0)), 100))
        except (TypeError, ValueError):
            data["percent"] = 0
        return data

    @classmethod
    def fallback(cls, job) -> dict[str, Any]:
        if job.status == job.STATUS_QUEUED:
            return {
                "job_id": job.id,
                "percent": 2,
                "stage": "queued",
                "message": "Excel kuyruğa alındı",
                "detail": "İşleme sırası bekleniyor",
                "status": job.status,
                "updated_at": job.queued_at.isoformat() if job.queued_at else None,
            }
        if job.status == job.STATUS_COMPLETED:
            return {
                "job_id": job.id,
                "percent": 100,
                "stage": "completed",
                "message": "IMS yüklemesi ve analiz ekranları hazır",
                "detail": None,
                "status": job.status,
                "updated_at": job.completed_at.isoformat() if job.completed_at else None,
            }
        if job.status == job.STATUS_FAILED:
            return {
                "job_id": job.id,
                "percent": 100,
                "stage": "failed",
                "message": "IMS yüklemesi tamamlanamadı",
                "detail": "Mevcut veriler korunmuştur",
                "status": job.status,
                "updated_at": job.completed_at.isoformat() if job.completed_at else None,
            }
        return {
            "job_id": job.id,
            "percent": 5,
            "stage": "processing",
            "message": "Dosya kontrol ediliyor",
            "detail": None,
            "status": job.status,
            "updated_at": job.started_at.isoformat() if job.started_at else None,
        }

    @classmethod
    def for_job(cls, job) -> dict[str, Any]:
        stored = cls.read(job.id)
        if stored is None:
            return cls.fallback(job)

        # A successful workbook transaction can be followed by durable dashboard
        # and representative snapshot warm-up. Keep that real progress visible
        # even though the queue row is already COMPLETED; only the final 100%
        # record switches the visible status to COMPLETED.
        if job.status == job.STATUS_COMPLETED:
            if (
                stored.get("status") == job.STATUS_PROCESSING
                and stored.get("stage") in cls.POST_IMPORT_STAGES
            ):
                return stored
            if stored.get("status") != job.status:
                return cls.fallback(job)
        elif job.status == job.STATUS_FAILED and stored.get("status") != job.status:
            return cls.fallback(job)
        return stored
