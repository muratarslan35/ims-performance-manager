"""Resource-aware Gunicorn settings for the single-server production host.

The application is read-heavy, while an IMS workbook import is a deliberately
serialized and potentially long request. A small number of threaded workers
keeps normal dashboards responsive without multiplying pandas/openpyxl memory
usage or creating unnecessary SQLite write contention.
"""

from __future__ import annotations

import multiprocessing
import os


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _available_memory_mb() -> int:
    """Return host memory in MiB without adding a runtime dependency."""
    try:
        with open("/proc/meminfo", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return 2048


def recommended_workers(cpu_count: int | None = None, memory_mb: int | None = None) -> int:
    """Choose a conservative worker count for SQLite and Excel workloads."""
    cpus = max(int(cpu_count or multiprocessing.cpu_count() or 1), 1)
    memory = max(int(memory_mb or _available_memory_mb()), 256)

    # Reserve memory for the OS, SQLite page cache and a simultaneous import.
    memory_cap = 2 if memory < 3072 else 3 if memory < 6144 else 4
    return max(2, min(cpus + 1, memory_cap, 4))


bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")
workers = _positive_int("GUNICORN_WORKERS", recommended_workers())
worker_class = "gthread"
threads = _positive_int("GUNICORN_THREADS", 3)

# A real workbook currently needs several minutes. Other threads/workers keep
# serving reads while the single import lock protects SQLite write semantics.
timeout = _positive_int("GUNICORN_TIMEOUT", 600)
graceful_timeout = _positive_int("GUNICORN_GRACEFUL_TIMEOUT", 60)
keepalive = _positive_int("GUNICORN_KEEPALIVE", 5)

# Do not force-recycle the worker in post_request for /ims/upload. Although
# post_request is invoked after the response iterator finishes, terminating the
# worker there can still tear down the client socket before the browser receives
# the final redirect/body, producing ERR_CONNECTION_ABORTED. Periodic Gunicorn
# recycling remains enabled below and bounds long-term fragmentation without
# sacrificing upload response delivery.
max_requests = _positive_int("GUNICORN_MAX_REQUESTS", 1000)
max_requests_jitter = _positive_int("GUNICORN_MAX_REQUESTS_JITTER", 100)

preload_app = False  # Never fork a process after opening SQLite engine state.
accesslog = "-"
errorlog = "-"
capture_output = True
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
