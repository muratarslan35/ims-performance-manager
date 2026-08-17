#!/usr/bin/env python3
"""Create a consistent SQLite backup while WAL mode and readers are active."""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup(source: Path, destination: Path) -> dict:
    if not source.is_file():
        raise FileNotFoundError(source)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)

    source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=30)
    destination_connection = sqlite3.connect(destination, timeout=30)
    try:
        source_connection.execute("PRAGMA busy_timeout=30000")
        destination_connection.execute("PRAGMA busy_timeout=30000")
        source_connection.backup(destination_connection, pages=256, sleep=0.05)
        destination_connection.commit()
        integrity = destination_connection.execute("PRAGMA integrity_check").fetchone()[0]
        if str(integrity).lower() != "ok":
            raise RuntimeError(f"SQLite backup integrity check failed: {integrity}")
    finally:
        destination_connection.close()
        source_connection.close()

    return {
        "source": str(source),
        "destination": str(destination),
        "destination_bytes": destination.stat().st_size,
        "destination_sha256": sha256(destination),
        "integrity_check": "ok",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = backup(args.source, args.destination)
    print("SQLITE_ONLINE_BACKUP|" + "|".join(f"{key}={value}" for key, value in result.items()))


if __name__ == "__main__":
    main()
