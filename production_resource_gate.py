#!/usr/bin/env python
"""Fail closed when the production host lacks safe import/deploy headroom."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def _meminfo(path: Path = Path("/proc/meminfo")) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, raw = line.split(":", 1)
        values[key] = int(raw.strip().split()[0]) * 1024
    return values


def snapshot(database: Path, *, acceptance_seconds: float | None = None) -> dict:
    memory = _meminfo()
    disk = os.statvfs(database.parent)
    cpu_count = os.cpu_count() or 1
    load1, load5, load15 = os.getloadavg()
    db_bytes = database.stat().st_size if database.exists() else 0
    wal = Path(f"{database}-wal")
    return {
        "cpu_count": cpu_count,
        "load1": load1,
        "load5": load5,
        "load15": load15,
        "load1_per_cpu": load1 / cpu_count,
        "memory_total_bytes": memory.get("MemTotal", 0),
        "memory_available_bytes": memory.get("MemAvailable", 0),
        "swap_total_bytes": memory.get("SwapTotal", 0),
        "swap_free_bytes": memory.get("SwapFree", 0),
        "disk_total_bytes": disk.f_blocks * disk.f_frsize,
        "disk_free_bytes": disk.f_bavail * disk.f_frsize,
        "inode_free_ratio": (disk.f_favail / disk.f_files) if disk.f_files else 1.0,
        "database_bytes": db_bytes,
        "wal_bytes": wal.stat().st_size if wal.exists() else 0,
        "acceptance_seconds": acceptance_seconds,
    }


def evaluate(
    data: dict,
    *,
    min_memory_mb: int = 96,
    min_disk_gb: float = 2.0,
    min_inode_percent: float = 5.0,
    max_load_per_cpu: float = 4.0,
    max_acceptance_seconds: float = 1500.0,
) -> list[str]:
    failures = []
    if data["memory_available_bytes"] < min_memory_mb * 1024**2:
        failures.append("memory_available")
    if data["disk_free_bytes"] < min_disk_gb * 1024**3:
        failures.append("disk_free")
    if data["inode_free_ratio"] < min_inode_percent / 100:
        failures.append("inode_free")
    if data["load1_per_cpu"] > max_load_per_cpu:
        failures.append("cpu_load")
    duration = data.get("acceptance_seconds")
    if duration is not None and duration > max_acceptance_seconds:
        failures.append("acceptance_duration")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("instance/ipm.db"))
    parser.add_argument("--acceptance-seconds", type=float)
    parser.add_argument("--min-memory-mb", type=int, default=96)
    parser.add_argument("--min-disk-gb", type=float, default=2.0)
    parser.add_argument("--min-inode-percent", type=float, default=5.0)
    parser.add_argument("--max-load-per-cpu", type=float, default=4.0)
    parser.add_argument("--max-acceptance-seconds", type=float, default=1500.0)
    args = parser.parse_args()
    data = snapshot(args.database, acceptance_seconds=args.acceptance_seconds)
    failures = evaluate(
        data,
        min_memory_mb=args.min_memory_mb,
        min_disk_gb=args.min_disk_gb,
        min_inode_percent=args.min_inode_percent,
        max_load_per_cpu=args.max_load_per_cpu,
        max_acceptance_seconds=args.max_acceptance_seconds,
    )
    data["failures"] = failures
    data["status"] = "PASS" if not failures else "FAIL"
    print("PRODUCTION_RESOURCE|" + json.dumps(data, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
