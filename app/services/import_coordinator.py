"""Cross-process coordination for heavyweight IMS workbook imports."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app

try:
    import fcntl
except ImportError:  # pragma: no cover - production and CI are Linux
    fcntl = None


class ImportBusyError(RuntimeError):
    def __init__(self, metadata=None):
        self.metadata = metadata or {}
        super().__init__("Başka bir IMS yüklemesi şu anda işleniyor.")


class ImportCoordinator:
    """Allow only one IMS writer at a time across threads/processes.

    SQLite supports many concurrent readers in WAL mode, but only one writer.
    A filesystem advisory lock makes that constraint explicit and predictable
    before the expensive ETL transaction starts.
    """

    @staticmethod
    def _lock_path() -> Path:
        root = Path(current_app.instance_path) / "locks"
        root.mkdir(parents=True, exist_ok=True)
        return root / "ims-import.lock"

    @staticmethod
    def _read_metadata(handle) -> dict:
        try:
            handle.seek(0)
            raw = handle.read().strip()
            return json.loads(raw) if raw else {}
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    @classmethod
    def status(cls) -> dict:
        """Return live lock state without trusting stale metadata on disk."""
        if fcntl is None:
            return {"active": False, "metadata": {}}

        lock_path = cls._lock_path()
        handle = lock_path.open("a+", encoding="utf-8")
        try:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {"active": True, "metadata": cls._read_metadata(handle)}

            # A process crash automatically releases flock but can leave its
            # descriptive JSON behind. Clear that stale text only after this
            # process proves that no live importer owns the lock.
            handle.seek(0)
            handle.truncate()
            handle.flush()
            os.fsync(handle.fileno())
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return {"active": False, "metadata": {}}
        finally:
            handle.close()

    @classmethod
    @contextmanager
    def acquire(cls, *, uploaded_by: str, file_name: str, wait_seconds: float = 2.0):
        if fcntl is None:
            raise RuntimeError("IMS import coordination requires a POSIX file lock implementation.")

        lock_path = cls._lock_path()
        handle = lock_path.open("a+", encoding="utf-8")
        deadline = time.monotonic() + max(float(wait_seconds), 0.0)

        acquired = False
        try:
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise ImportBusyError(cls._read_metadata(handle))
                    time.sleep(0.1)

            metadata = {
                "pid": os.getpid(),
                "uploaded_by": uploaded_by,
                "file_name": file_name,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps(metadata, ensure_ascii=False))
            handle.flush()
            os.fsync(handle.fileno())

            current_app.logger.info("ims_import_lock_acquired %s", metadata)
            yield metadata
        finally:
            if acquired:
                try:
                    handle.seek(0)
                    handle.truncate()
                    handle.flush()
                    os.fsync(handle.fileno())
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                current_app.logger.info("ims_import_lock_released file=%s", file_name)
            handle.close()
