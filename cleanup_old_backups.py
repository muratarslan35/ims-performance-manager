#!/usr/bin/env python
"""Safely retain validated SQLite rollback backup sets.

Managed backup sets share a timestamp:
- ipm-predeploy-<stamp>.db
- users-predeploy-<stamp>.db
- ipm-pre-competition-backfill-<stamp>.db

Cleanup validates the primary/user databases for every retained set before
removing anything. Production maintenance normally keeps the latest two
complete rollback sets so storage stays bounded without giving up the most
recent fallback generation.
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
DATABASE_BACKUP_RE = re.compile(r".+\.db(?:-(?:wal|shm))?$")
REQUIRED_KINDS = {"ipm-predeploy", "users-predeploy"}


def integrity_ok(path: Path) -> bool:
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        return bool(result) and str(result[0]).lower() == "ok"
    finally:
        connection.close()


def _managed_entries(backup_dir: Path):
    managed: list[tuple[Path, str, str]] = []
    unmanaged_paths: list[Path] = []
    for path in sorted(backup_dir.iterdir()):
        if not path.is_file():
            continue
        match = MANAGED_RE.match(path.name)
        if match:
            managed.append((path, match.group("kind"), match.group("stamp")))
        else:
            unmanaged_paths.append(path)
    return managed, unmanaged_paths


def _complete_stamps(managed: list[tuple[Path, str, str]]) -> list[str]:
    kinds_by_stamp: dict[str, set[str]] = {}
    for path, kind, stamp in managed:
        if path.name.endswith(".db"):
            kinds_by_stamp.setdefault(stamp, set()).add(kind)
    return sorted(
        stamp for stamp, kinds in kinds_by_stamp.items()
        if REQUIRED_KINDS.issubset(kinds)
    )


def cleanup(
    backup_dir: Path,
    keep_stamp: str | None = None,
    *,
    keep_latest: int | None = None,
    dry_run: bool = False,
    purge_unmanaged_db: bool = False,
) -> dict:
    backup_dir = backup_dir.resolve()
    if not backup_dir.is_dir():
        raise RuntimeError(f"Backup directory not found: {backup_dir}")
    if keep_stamp and keep_latest:
        raise RuntimeError("Choose either keep_stamp or keep_latest, not both")
    if not keep_stamp and not keep_latest:
        raise RuntimeError("A retention selector is required")
    if keep_stamp and not re.fullmatch(r"\d{8}-\d{6}", keep_stamp):
        raise RuntimeError(f"Invalid keep timestamp: {keep_stamp}")
    if keep_latest is not None and keep_latest < 1:
        raise RuntimeError("keep_latest must be at least 1")

    managed, unmanaged_paths = _managed_entries(backup_dir)
    complete_stamps = _complete_stamps(managed)

    if keep_stamp:
        keep_stamps = [keep_stamp]
    else:
        keep_stamps = complete_stamps[-int(keep_latest):]
        if not keep_stamps:
            raise RuntimeError("Refusing cleanup: no complete rollback backup set found")

    for stamp in keep_stamps:
        retained = [(path, kind) for path, kind, item_stamp in managed if item_stamp == stamp]
        retained_kinds = {kind for path, kind in retained if path.name.endswith(".db")}
        missing = sorted(REQUIRED_KINDS - retained_kinds)
        if missing:
            raise RuntimeError(
                f"Refusing cleanup: retained rollback set {stamp} is incomplete; missing "
                + ", ".join(missing)
            )
        primary_paths = {
            kind: path
            for path, kind in retained
            if kind in REQUIRED_KINDS and path.name.endswith(".db")
        }
        failed_integrity = [kind for kind, path in primary_paths.items() if not integrity_ok(path)]
        if failed_integrity:
            raise RuntimeError(
                f"Refusing cleanup: retained backup integrity failed for {stamp}: "
                + ", ".join(failed_integrity)
            )

    keep_set = set(keep_stamps)
    managed_deletions = [path for path, _kind, stamp in managed if stamp not in keep_set]
    unmanaged_db_deletions = (
        [path for path in unmanaged_paths if DATABASE_BACKUP_RE.fullmatch(path.name)]
        if purge_unmanaged_db
        else []
    )
    deletions = managed_deletions + unmanaged_db_deletions

    bytes_to_delete = sum(path.stat().st_size for path in deletions)
    before_bytes = sum(path.stat().st_size for path in backup_dir.iterdir() if path.is_file())

    if not dry_run:
        for path in deletions:
            path.unlink()

    remaining_files = sorted(path.name for path in backup_dir.iterdir() if path.is_file())
    after_bytes = before_bytes if dry_run else before_bytes - bytes_to_delete
    retained_managed = sorted(
        path.name for path, _kind, stamp in managed if stamp in keep_set
    )
    unmanaged_preserved = sorted(
        path.name
        for path in unmanaged_paths
        if path not in unmanaged_db_deletions or dry_run
    )

    payload = {
        "result": "PASS",
        "backup_dir": str(backup_dir),
        "keep_stamp": keep_stamp,
        "keep_latest": keep_latest,
        "keep_stamps": keep_stamps,
        "dry_run": dry_run,
        "purge_unmanaged_db": purge_unmanaged_db,
        "deleted_files": 0 if dry_run else len(deletions),
        "would_delete_files": len(deletions),
        "deleted_bytes": 0 if dry_run else bytes_to_delete,
        "would_delete_bytes": bytes_to_delete,
        "bytes_before": before_bytes,
        "bytes_after": after_bytes,
        "managed_deleted": 0 if dry_run else len(managed_deletions),
        "unmanaged_db_deleted": 0 if dry_run else len(unmanaged_db_deletions),
        "retained_managed": retained_managed,
        "unmanaged_preserved": unmanaged_preserved,
        "remaining_files": remaining_files,
        "retained_integrity": {stamp: "ok" for stamp in keep_stamps},
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup-dir", default="instance/backups")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--keep-stamp")
    selector.add_argument("--keep-latest", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--purge-unmanaged-db", action="store_true")
    args = parser.parse_args()

    payload = cleanup(
        Path(args.backup_dir),
        args.keep_stamp,
        keep_latest=args.keep_latest,
        dry_run=args.dry_run,
        purge_unmanaged_db=args.purge_unmanaged_db,
    )
    print("BACKUP_RETENTION|" + json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
