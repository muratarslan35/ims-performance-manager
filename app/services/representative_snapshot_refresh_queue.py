"""Persistent queue for representative read-model refreshes after production results.

Production uploads are accepted by the web process, while heavy representative
snapshot generation belongs to the existing single IMS worker.  A tiny
filesystem queue keeps that work durable, serial, and behind any IMS job already
in progress.  No business rows are stored here.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app

from app.models import IMSUpload


class RepresentativeSnapshotRefreshQueue:
    @staticmethod
    def _root() -> Path:
        root = Path(current_app.instance_path) / "representative_refresh_queue"
        root.mkdir(parents=True, exist_ok=True)
        return root

    @classmethod
    def _path(cls, year: int, month: int) -> Path:
        return cls._root() / f"{int(year):04d}-{int(month):02d}.json"

    @staticmethod
    def _shift_month(year: int, month: int, delta: int = 1) -> tuple[int, int]:
        ordinal = int(year) * 12 + int(month) - 1 + int(delta)
        return ordinal // 12, ordinal % 12 + 1

    @classmethod
    def enqueue(cls, year: int, month: int, *, reason: str) -> dict:
        year, month = int(year), int(month)
        payload = {
            "year": year,
            "month": month,
            "reason": str(reason),
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }
        target = cls._path(year, month)
        temporary = target.with_suffix(f".json.tmp-{os.getpid()}")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, target)
        return payload

    @classmethod
    def enqueue_for_production(cls, year: int, month: int, production_upload_id: int) -> list[dict]:
        """Refresh the production month and, when already open, its successor.

        The successor snapshot contains the production month as its "previous
        month" comparison. If that next month has not started yet, its first IMS
        snapshot will naturally consume the finalized production result.
        """
        reason = f"production_upload:{int(production_upload_id)}"
        queued = [cls.enqueue(year, month, reason=reason)]
        next_year, next_month = cls._shift_month(year, month, 1)
        next_exists = IMSUpload.query.filter_by(
            year=next_year,
            month=next_month,
            status=IMSUpload.STATUS_COMPLETED,
        ).first()
        if next_exists is not None:
            queued.append(cls.enqueue(next_year, next_month, reason=reason))
        return queued

    @classmethod
    def next(cls) -> dict | None:
        paths = sorted(
            cls._root().glob("????-??.json"),
            key=lambda path: (path.stat().st_mtime, path.name),
        )
        for path in paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["_path"] = str(path)
                return payload
            except (OSError, ValueError, json.JSONDecodeError):
                path.unlink(missing_ok=True)
        return None

    @classmethod
    def complete(cls, item: dict) -> None:
        path = Path(str(item.get("_path") or ""))
        if path:
            path.unlink(missing_ok=True)
