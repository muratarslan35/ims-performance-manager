"""Bounded stack probe for the isolated production-host IMS queue benchmark.

This helper never touches the live database directly. The existing benchmark
workflow still creates an isolated /tmp SQLite copy first. While that benchmark
runs, Python stack traces are emitted every 60 seconds so an uninstrumented gap
can be attributed to the exact function/line. A hard seven-minute process bound
keeps this diagnostic intentionally short.
"""
from __future__ import annotations

import faulthandler
import importlib.util
import os
import threading
from pathlib import Path


HARNESS = Path("/tmp/ims-queue-benchmark-once.py")
HARD_LIMIT_SECONDS = 420


def _load_harness():
    spec = importlib.util.spec_from_file_location("ims_queue_benchmark_once", HARNESS)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Benchmark harness yüklenemedi: {HARNESS}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hard_stop() -> None:
    print(
        f"IMS_QUEUE_STACK_PROBE_TIMEOUT|seconds={HARD_LIMIT_SECONDS}",
        flush=True,
    )
    faulthandler.dump_traceback(all_threads=True)
    os._exit(124)


def main() -> int:
    faulthandler.enable(all_threads=True)
    faulthandler.dump_traceback_later(60, repeat=True)
    timer = threading.Timer(HARD_LIMIT_SECONDS, _hard_stop)
    timer.daemon = True
    timer.start()
    try:
        module = _load_harness()
        return int(module.main() or 0)
    finally:
        timer.cancel()
        faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    raise SystemExit(main())
