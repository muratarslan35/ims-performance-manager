"""Persistent report read-model and export artifact cache.

Reports are derived from immutable representative snapshots. This cache turns a
large number of concurrent report requests into one snapshot aggregation per
unique source generation + filter combination. Cache files live outside the
business database, are atomically replaced and are safe to share across
Gunicorn workers.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import current_app

from app.services.persistent_representative_snapshot_service import (
    PersistentRepresentativeSnapshotService,
)


class ReportCacheService:
    VERSION = 3

    @classmethod
    def _root(cls) -> Path:
        configured = current_app.config.get("REPORT_CACHE_FOLDER")
        root = Path(configured) if configured else Path(current_app.instance_path) / "report_cache"
        (root / "read_models").mkdir(parents=True, exist_ok=True)
        (root / "options").mkdir(parents=True, exist_ok=True)
        (root / "exports").mkdir(parents=True, exist_ok=True)
        (root / "locks").mkdir(parents=True, exist_ok=True)
        return root

    @classmethod
    def source_sets(cls, service) -> list[dict[str, int]]:
        rows = []
        for year, month in service.months():
            set_id = PersistentRepresentativeSnapshotService._visible_set_id(year, month)
            rows.append({"year": int(year), "month": int(month), "set_id": int(set_id or 0)})
        return rows

    @classmethod
    def identity(cls, service) -> tuple[str, dict[str, Any]]:
        raw_scope_values = list(getattr(service, "scope_values", None) or [service.scope_value])
        if service.scope == "region":
            scope_values = sorted({
                service._region_code(value) or str(value).strip()
                for value in raw_scope_values if str(value or "").strip()
            })
        elif service.scope == "city":
            scope_values = sorted({
                service._scope_key(value)
                for value in raw_scope_values if str(value or "").strip()
            })
        elif service.scope == "representative":
            scope_values = sorted({
                str(int(value)) for value in raw_scope_values if str(value).isdigit()
            }, key=int)
        else:
            scope_values = []
        payload = {
            "version": cls.VERSION,
            "year": int(service.year),
            "month": int(service.month),
            "period": str(service.period),
            "scope": str(service.scope),
            "scope_values": scope_values,
            "product_ids": sorted(int(value) for value in service.product_ids),
            "source_sets": cls.source_sets(service),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest(), payload

    @classmethod
    def _read_model_path(cls, cache_key: str) -> Path:
        return cls._root() / "read_models" / f"{cache_key}.json"

    @classmethod
    def _options_identity(cls, service) -> str:
        payload = {
            "version": cls.VERSION,
            "year": int(service.year),
            "month": int(service.month),
            "period": str(service.period),
            "source_sets": cls.source_sets(service),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(("options|" + raw).encode("utf-8")).hexdigest()

    @classmethod
    def _options_path(cls, cache_key: str) -> Path:
        return cls._root() / "options" / f"{cache_key}.json"

    @classmethod
    def _lock_path(cls, cache_key: str) -> Path:
        return cls._root() / "locks" / f"{cache_key}.lock"

    @classmethod
    def export_path(cls, cache_key: str, file_type: str) -> Path:
        if file_type not in {"pdf", "xlsx", "pptx"}:
            raise ValueError("unsupported report export type")
        return cls._root() / "exports" / f"{cache_key}.{file_type}"

    @staticmethod
    def _json_default(value):
        if isinstance(value, datetime):
            return value.isoformat()
        raise TypeError(f"Unsupported report cache value: {type(value)!r}")

    @classmethod
    def _atomic_json_write(cls, path: Path, payload: dict) -> None:
        tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                separators=(",", ":"),
                default=cls._json_default,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)

    @classmethod
    def _atomic_bytes_write(cls, path: Path, payload: bytes) -> None:
        tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        with tmp.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)

    @classmethod
    def read_by_key(cls, cache_key: str) -> dict | None:
        path = cls._read_model_path(cache_key)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    @classmethod
    def get_filter_options(cls, service) -> dict:
        cache_key = cls._options_identity(service)
        path = cls._options_path(cache_key)
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                pass

        lock_path = cls._lock_path("options-" + cache_key)
        with lock_path.open("a+") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            if path.is_file():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError, json.JSONDecodeError):
                    pass

            options = service.filter_options()
            payload = {
                "products": [
                    {"id": int(item.id), "product_name": str(item.product_name)}
                    for item in options["products"]
                ],
                "regions": options["regions"],
                "cities": options["cities"],
                "representatives": [
                    {
                        "id": int(item.id),
                        "rep_name": str(item.rep_name),
                        "region": str(item.region or ""),
                        "region_code": service._region_code(item.region) or str(item.region or ""),
                        "region_label": service._region_label(item.region),
                        "city": str(item.city or ""),
                    }
                    for item in options["representatives"]
                ],
            }
            cls._atomic_json_write(path, payload)
            return payload

    @classmethod
    def get_or_build(cls, service) -> tuple[dict, str, bool]:
        cache_key, identity = cls.identity(service)
        cached = cls.read_by_key(cache_key)
        if cached is not None:
            return cached, cache_key, False

        lock_path = cls._lock_path(cache_key)
        with lock_path.open("a+") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            cached = cls.read_by_key(cache_key)
            if cached is not None:
                return cached, cache_key, False

            report = service.build()
            report["_cache"] = {
                "key": cache_key,
                "version": cls.VERSION,
                "source_sets": identity["source_sets"],
            }
            cls._atomic_json_write(cls._read_model_path(cache_key), report)
            return report, cache_key, True

    @classmethod
    def write_export(cls, cache_key: str, file_type: str, payload: bytes) -> Path:
        path = cls.export_path(cache_key, file_type)
        cls._atomic_bytes_write(path, payload)
        return path

    @classmethod
    def cached_export(cls, cache_key: str, file_type: str) -> Path | None:
        path = cls.export_path(cache_key, file_type)
        return path if path.is_file() and path.stat().st_size > 0 else None

    @classmethod
    def prune(cls, *, max_age_days: int = 45, max_files: int = 2000) -> dict[str, int]:
        root = cls._root()
        cutoff = datetime.now().timestamp() - max_age_days * 86400
        removed = 0
        for folder in (root / "read_models", root / "options", root / "exports"):
            files = [path for path in folder.iterdir() if path.is_file()]
            for path in files:
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink(missing_ok=True)
                        removed += 1
                except OSError:
                    pass
            files = sorted(
                (path for path in folder.iterdir() if path.is_file()),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            for path in files[max_files:]:
                try:
                    path.unlink(missing_ok=True)
                    removed += 1
                except OSError:
                    pass
        return {"removed": removed}
