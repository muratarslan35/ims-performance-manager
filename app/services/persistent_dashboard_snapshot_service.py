"""Cross-worker durable dashboard snapshot storage.

The dashboard's business calculations remain owned by ``DashboardService``.
This service only persists an already-built payload and serves it back when the
latest IMS / production source identity is still identical. A small atomic JSON
file is used instead of process-local RAM so all Gunicorn workers reuse the same
ready payload after an import.
"""
from __future__ import annotations

import fcntl
import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from flask import current_app
from sqlalchemy import desc

from app.extensions import db
from app.models import IMSUpload
from app.services.production_result_service import ProductionResultService


class PersistentDashboardSnapshotService:
    VERSION = 1

    @classmethod
    def source_identity(cls, year: int, month: int) -> tuple[int, int]:
        ims_id = db.session.query(IMSUpload.id).filter(
            IMSUpload.year == int(year),
            IMSUpload.month == int(month),
            IMSUpload.status == "COMPLETED",
        ).order_by(
            desc(IMSUpload.week_number),
            desc(IMSUpload.completed_at),
            desc(IMSUpload.id),
        ).limit(1).scalar()
        production_upload = ProductionResultService.final_upload(int(year), int(month))
        return int(ims_id or 0), int(production_upload.id if production_upload is not None else 0)

    @classmethod
    def _path(cls, year: int, month: int) -> Path:
        root = Path(current_app.instance_path) / "dashboard_snapshots"
        return root / f"dashboard-{int(year):04d}-{int(month):02d}.json"

    @classmethod
    def _lock_path(cls, year: int, month: int) -> Path:
        return cls._path(year, month).with_suffix(".lock")

    @classmethod
    def _json_ready(cls, value: Any) -> Any:
        if isinstance(value, dict):
            ready = {}
            for key, item in value.items():
                if isinstance(key, tuple):
                    key = "|".join(str(part) for part in key)
                elif key is not None and not isinstance(key, (str, int, float, bool)):
                    key = str(key)
                ready[key] = cls._json_ready(item)
            return ready
        if isinstance(value, (list, tuple)):
            return [cls._json_ready(item) for item in value]
        if isinstance(value, set):
            return [cls._json_ready(item) for item in sorted(value, key=str)]
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return value

    @classmethod
    def get_active(cls, year: int, month: int) -> dict | None:
        path = cls._path(year, month)
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return None

        ims_id, production_id = cls.source_identity(year, month)
        if (
            envelope.get("version") != cls.VERSION
            or int(envelope.get("year", 0)) != int(year)
            or int(envelope.get("month", 0)) != int(month)
            or int(envelope.get("ims_upload_id", -1)) != ims_id
            or int(envelope.get("production_upload_id", -1)) != production_id
        ):
            return None
        payload = envelope.get("payload")
        return payload if isinstance(payload, dict) else None

    @classmethod
    def publish(cls, year: int, month: int, payload: dict) -> dict:
        ims_id, production_id = cls.source_identity(year, month)
        path = cls._path(year, month)
        path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {
            "version": cls.VERSION,
            "year": int(year),
            "month": int(month),
            "ims_upload_id": ims_id,
            "production_upload_id": production_id,
            "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "payload": cls._json_ready(payload),
        }
        temp_path = path.with_suffix(f".json.tmp-{os.getpid()}")
        temp_path.write_text(
            json.dumps(envelope, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temp_path, path)
        return {
            "status": "ACTIVE",
            "year": int(year),
            "month": int(month),
            "ims_upload_id": ims_id,
            "production_upload_id": production_id,
            "path": str(path),
        }

    @classmethod
    def get_or_build(cls, year: int, month: int, builder: Callable[[], dict]) -> tuple[dict, bool]:
        """Return a ready payload; allow only one process to perform a cold rebuild.

        The first caller after an IMS/source identity change owns the file lock.
        Other Gunicorn workers wait on that same lock, then read the newly
        published payload instead of launching duplicate OLAP/AI/prime queries.
        ``built`` is True only for the process that executed ``builder``.
        """
        active = cls.get_active(year, month)
        if active is not None:
            return active, False

        lock_path = cls._lock_path(year, month)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                active = cls.get_active(year, month)
                if active is not None:
                    return active, False
                payload = builder()
                cls.publish(year, month, payload)
                return payload, True
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
