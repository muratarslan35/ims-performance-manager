"""Durable source-versioned fallback for historical region pages.

Some early periods predate the persistent region snapshot tables.  Their legacy
business calculation remains authoritative, but it must not run again for every
user request.  This service calculates one complete historical region read model
per IMS/production source identity and persists it atomically for all Gunicorn
workers.  A later IMS or production upload changes the identity and naturally
creates a fresh generation without invalidating older rollback data.
"""
from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime
from hashlib import sha1
from pathlib import Path

from flask import current_app

from app.services.persistent_region_snapshot_service import (
    PersistentRegionSnapshotService,
)


class HistoricalRegionReadModelService:
    VERSION = 1

    @classmethod
    def _region_token(cls, region_key) -> str:
        value = str(region_key or "").strip()
        digest = sha1(value.encode("utf-8")).hexdigest()[:16]
        return f"{digest}"

    @classmethod
    def _root(cls) -> Path:
        return Path(current_app.instance_path) / "historical_region_read_models"

    @classmethod
    def _path(
        cls,
        region_key,
        year: int,
        month: int,
        ims_id: int,
        production_id: int,
    ) -> Path:
        return cls._root() / (
            f"region-{int(year):04d}-{int(month):02d}-"
            f"{cls._region_token(region_key)}-ims{int(ims_id)}-"
            f"production{int(production_id)}.json"
        )

    @classmethod
    def _lock_path(cls, region_key, year: int, month: int) -> Path:
        return cls._root() / (
            f"region-{int(year):04d}-{int(month):02d}-"
            f"{cls._region_token(region_key)}.lock"
        )

    @classmethod
    def _read_identity(
        cls,
        region_key,
        year: int,
        month: int,
        ims_id: int,
        production_id: int,
    ):
        path = cls._path(region_key, year, month, ims_id, production_id)
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return None
        if (
            int(envelope.get("version") or 0) != cls.VERSION
            or int(envelope.get("year") or 0) != int(year)
            or int(envelope.get("month") or 0) != int(month)
            or str(envelope.get("region_key") or "").strip()
            != str(region_key or "").strip()
            or int(envelope.get("ims_upload_id") or 0) != int(ims_id)
            or int(envelope.get("production_upload_id") or 0)
            != int(production_id)
            or not isinstance(envelope.get("payload"), dict)
        ):
            return None
        return envelope["payload"]

    @classmethod
    def get_active(cls, region_key, year: int, month: int):
        ims_id, production_id = PersistentRegionSnapshotService.source_identity(
            int(year), int(month)
        )
        if not ims_id:
            return None
        return cls._read_identity(
            region_key, year, month, ims_id, production_id
        )

    @classmethod
    def _build_authoritative(cls, region_key, year: int, month: int):
        # Imports stay local so this persistence layer does not alter service
        # initialization order or the authoritative calculation implementation.
        from app.services.region_market_service import RegionMarketService
        from app.services.region_performance_service import RegionPerformanceService
        from app.services.scoped_ai_insight_service import ScopedAIInsightService

        performance = RegionPerformanceService(region_key, year, month)
        report = performance.report()
        market_analysis = RegionMarketService(
            report["region_key"], performance.rep_ids, year, month
        ).build()
        return {
            "report": report,
            "market_analysis": market_analysis,
            "ai_report": ScopedAIInsightService.build(
                scope_type="region",
                scope_name=report["region_name"],
                periods=report["periods"],
                market_analysis=market_analysis,
            ),
        }

    @classmethod
    def get_or_build(cls, region_key, year: int, month: int):
        """Return one source-versioned historical payload across all workers."""
        year, month = int(year), int(month)
        ims_id, production_id = PersistentRegionSnapshotService.source_identity(
            year, month
        )
        if not ims_id:
            raise ValueError("Seçili dönem için tamamlanmış IMS verisi bulunamadı.")

        ready = cls._read_identity(
            region_key, year, month, ims_id, production_id
        )
        if ready is not None:
            return ready

        lock_path = cls._lock_path(region_key, year, month)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                ready = cls._read_identity(
                    region_key, year, month, ims_id, production_id
                )
                if ready is not None:
                    return ready

                payload = cls._build_authoritative(region_key, year, month)
                envelope = {
                    "version": cls.VERSION,
                    "year": year,
                    "month": month,
                    "region_key": str(region_key or "").strip(),
                    "ims_upload_id": int(ims_id),
                    "production_upload_id": int(production_id),
                    "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    "payload": PersistentRegionSnapshotService._json_ready(payload),
                }
                path = cls._path(
                    region_key, year, month, ims_id, production_id
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_suffix(f".json.tmp-{os.getpid()}")
                temp.write_text(
                    json.dumps(
                        envelope,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=PersistentRegionSnapshotService._json_default,
                    ),
                    encoding="utf-8",
                )
                os.replace(temp, path)
                return envelope["payload"]
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
