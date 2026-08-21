"""Serialize database/bootstrap reconciliation across WSGI worker startup."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - production and CI are Linux
    fcntl = None


class StartupCoordinator:
    @staticmethod
    @contextmanager
    def acquire(app):
        """Prevent concurrent workers from racing on idempotent seed writes."""
        if fcntl is None:
            yield
            return

        lock_root = Path(app.instance_path) / "locks"
        lock_root.mkdir(parents=True, exist_ok=True)
        handle = (lock_root / "application-startup.lock").open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
