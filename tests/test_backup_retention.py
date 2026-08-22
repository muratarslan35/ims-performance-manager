import sqlite3
from pathlib import Path

import pytest

from cleanup_old_backups import cleanup


def make_db(path: Path):
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO sample(value) VALUES ('ok')")
        connection.commit()
    finally:
        connection.close()


def make_set(root: Path, stamp: str):
    make_db(root / f"ipm-predeploy-{stamp}.db")
    make_db(root / f"users-predeploy-{stamp}.db")
    make_db(root / f"ipm-pre-competition-backfill-{stamp}.db")


def test_cleanup_keeps_only_requested_managed_rollback_set(tmp_path):
    make_set(tmp_path, "20260820-100000")
    make_set(tmp_path, "20260821-100000")
    make_set(tmp_path, "20260822-100000")
    manual = tmp_path / "manual-do-not-delete.db"
    make_db(manual)

    result = cleanup(tmp_path, "20260822-100000")

    assert result["result"] == "PASS"
    assert result["deleted_files"] == 6
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "ipm-pre-competition-backfill-20260822-100000.db",
        "ipm-predeploy-20260822-100000.db",
        "manual-do-not-delete.db",
        "users-predeploy-20260822-100000.db",
    ]
    assert result["unmanaged_preserved"] == ["manual-do-not-delete.db"]
    assert result["retained_integrity"] == {
        "ipm-predeploy": "ok",
        "users-predeploy": "ok",
    }


def test_cleanup_refuses_incomplete_retained_set(tmp_path):
    make_set(tmp_path, "20260820-100000")
    make_db(tmp_path / "ipm-predeploy-20260822-100000.db")

    with pytest.raises(RuntimeError, match="incomplete"):
        cleanup(tmp_path, "20260822-100000")

    assert (tmp_path / "ipm-predeploy-20260820-100000.db").exists()


def test_cleanup_refuses_corrupt_retained_backup_before_deleting(tmp_path):
    make_set(tmp_path, "20260820-100000")
    make_set(tmp_path, "20260822-100000")
    (tmp_path / "ipm-predeploy-20260822-100000.db").write_bytes(b"not sqlite")

    with pytest.raises(sqlite3.DatabaseError):
        cleanup(tmp_path, "20260822-100000")

    assert (tmp_path / "ipm-predeploy-20260820-100000.db").exists()


def test_cleanup_dry_run_never_deletes(tmp_path):
    make_set(tmp_path, "20260820-100000")
    make_set(tmp_path, "20260822-100000")

    result = cleanup(tmp_path, "20260822-100000", dry_run=True)

    assert result["deleted_files"] == 0
    assert result["would_delete_files"] == 3
    assert len(list(tmp_path.iterdir())) == 6
