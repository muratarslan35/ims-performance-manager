#!/usr/bin/env python
"""Safely retain only the current rollback backup set.

The deployment creates three managed SQLite backups with a shared timestamp:
- ipm-predeploy-<stamp>.db
- users-predeploy-<stamp>.db
- ipm-pre-competition-backfill-<stamp>.db

This utility validates the retained primary/user backups first, then deletes only
older files that match those managed naming schemes. Unknown/manual files are
never deleted automatically.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

MANAGED_RE = re.compile(
    r"^(?P<kind>ipm-predeploy|users-predeploy|ipm-pre-competition-backfill)-"
    r"(?P<stamp>\d{8}-\d{6})\.db(?P<sidecar>-(?:wal|shm))?$"
)
REQUIRED_KINDS = {"ipm-predeploy", "users-predeploy"}


def integrity_ok(path: Path) -> bool:
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        return bool(result) and str(result[0]).lower() == "ok"
    finally:
        connection.close()


def cleanup(backup_dir: Path, keep_stamp: str, *, dry_run: bool = False) -> dict:
    backup_dir = backup_dir.resolve()
    if not backup_dir.is_dir():
        raise RuntimeError(f"Backup directory not found: {backup_dir}")
    if not re.fullmatch(r"\d{8}-\d{6}", keep_stamp):
        raise RuntimeError(f"Invalid keep timestamp: {keep_stamp}")

    managed: list[tuple[Path, str, str]] = []
    unmanaged: list[str] = []
    for path in sorted(backup_dir.iterdir()):
        if not path.is_file():
            continue
        match = MANAGED_RE.match(path.name)
        if match:
            managed.append((path, match.group("kind"), match.group("stamp")))
        else:
            unmanaged.append(path.name)

    retained = [(path, kind) for path, kind, stamp in managed if stamp == keep_stamp]
    retained_kinds = {kind for path, kind in retained if path.name.endswith(".db")}
    missing = sorted(REQUIRED_KINDS - retained_kinds)
    if missing:
        raise RuntimeError(
            "Refusing cleanup: retained rollback set is incomplete; missing " + ", ".join(missing)
        )

    primary_paths = {
        kind: path
        for path, kind in retained
        if kind in REQUIRED_KINDS and path.name.endswith(".db")
    }
    failed_integrity = [kind for kind, path in primary_paths.items() if not integrity_ok(path)]
    if failed_integrity:
        raise RuntimeError(
            "Refusing cleanup: retained backup integrity failed for " + ", ".join(failed_integrity)
        )

    deletions = [path for path, _kind, stamp in managed if stamp != keep_stamp]
    bytes_to_delete = sum(path.stat().st_size for path in deletions)
    before_bytes = sum(path.stat().st_size for path, _kind, _stamp in managed)

    if not dry_run:
        for path in deletions:
            path.unlink()

    remaining_managed = [
        path.name
        for path, _kind, stamp in managed
        if stamp == keep_stamp or (dry_run and stamp != keep_stamp)
    ]
    after_bytes = before_bytes if dry_run else before_bytes - bytes_to_delete
    payload = {
        "result": "PASS",
        "backup_dir": str(backup_dir),
        "keep_stamp": keep_stamp,
        "dry_run": dry_run,
        "deleted_files": 0 if dry_run else len(deletions),
        "would_delete_files": len(deletions),
        "deleted_bytes": 0 if dry_run else bytes_to_delete,
        "would_delete_bytes": bytes_to_delete,
        "managed_bytes_before": before_bytes,
        "managed_bytes_after": after_bytes,
        "retained_managed": sorted(remaining_managed),
        "unmanaged_preserved": sorted(unmanaged),
        "retained_integrity": {kind: "ok" for kind in sorted(primary_paths)},
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup-dir", default="instance/backups")
    parser.add_argument("--keep-stamp", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    payload = cleanup(Path(args.backup_dir), args.keep_stamp, dry_run=args.dry_run)
    print("BACKUP_RETENTION|" + json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
