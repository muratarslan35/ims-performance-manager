"""SQLite runtime hardening for a single-server IMS deployment.

The IMS import pipeline intentionally commits atomically. SQLite therefore has
one long-lived writer while a workbook is being finalized. WAL mode lets normal
application reads continue during that writer, while busy_timeout gives short
competing writes a bounded wait instead of an immediate ``database is locked``.

Foreign-key enforcement is deliberately left at the application's existing
behaviour because legacy migrations and sentinel rows depend on it being off.
This module changes concurrency and read-performance semantics only, not
historical business-data rules.
"""

from __future__ import annotations

import sqlite3
import threading

from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.extensions import db


_LISTENER_LOCK = threading.Lock()
_LISTENER_INSTALLED = False
BUSY_TIMEOUT_MS = 30_000
CACHE_SIZE_KIB = 32 * 1024
MMAP_SIZE_BYTES = 256 * 1024 * 1024
JOURNAL_SIZE_LIMIT_BYTES = 64 * 1024 * 1024
WAL_AUTOCHECKPOINT_PAGES = 1000


def _apply_connection_pragmas(cursor) -> None:
    cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute(f"PRAGMA wal_autocheckpoint={WAL_AUTOCHECKPOINT_PAGES}")
    # Negative cache_size is kibibytes.  32 MiB per active connection keeps the
    # hot B-tree pages resident without allowing six Gunicorn threads to consume
    # unbounded memory.
    cursor.execute(f"PRAGMA cache_size=-{CACHE_SIZE_KIB}")
    # Memory mapping materially reduces syscall/page-cache churn for the large,
    # read-mostly competition table.  SQLite treats this as an upper bound.
    cursor.execute(f"PRAGMA mmap_size={MMAP_SIZE_BYTES}")
    cursor.execute("PRAGMA temp_store=MEMORY")
    # Keep checkpointed WAL files bounded after large imports while still
    # allowing the WAL to grow temporarily when readers hold old snapshots.
    cursor.execute(f"PRAGMA journal_size_limit={JOURNAL_SIZE_LIMIT_BYTES}")


def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return

    cursor = dbapi_connection.cursor()
    try:
        _apply_connection_pragmas(cursor)
    finally:
        cursor.close()


def install_sqlite_connection_pragmas() -> None:
    """Install the DB-API connection hook exactly once per Python process."""
    global _LISTENER_INSTALLED
    if _LISTENER_INSTALLED:
        return
    with _LISTENER_LOCK:
        if _LISTENER_INSTALLED:
            return
        event.listen(Engine, "connect", _configure_sqlite_connection)
        _LISTENER_INSTALLED = True


def configure_sqlite_runtime(app) -> dict:
    """Enable WAL for the configured SQLite database and return diagnostics.

    ``journal_mode=WAL`` is persistent in the database file. We still execute
    the statement at startup so a restored/copied database is automatically
    brought back to the expected production mode before writable traffic.
    """
    uri = str(app.config.get("SQLALCHEMY_DATABASE_URI", ""))
    if not uri.startswith("sqlite:"):
        return {"database": "non-sqlite", "journal_mode": None, "busy_timeout_ms": None}

    with app.app_context():
        with db.engine.connect() as connection:
            journal_mode = connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar()
            for statement in (
                f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}",
                "PRAGMA synchronous=NORMAL",
                f"PRAGMA wal_autocheckpoint={WAL_AUTOCHECKPOINT_PAGES}",
                f"PRAGMA cache_size=-{CACHE_SIZE_KIB}",
                f"PRAGMA mmap_size={MMAP_SIZE_BYTES}",
                "PRAGMA temp_store=MEMORY",
                f"PRAGMA journal_size_limit={JOURNAL_SIZE_LIMIT_BYTES}",
            ):
                connection.exec_driver_sql(statement)
            # Let SQLite decide whether statistics need refreshing.  This is
            # intentionally lightweight; full ANALYZE/VACUUM is not run at boot.
            connection.exec_driver_sql("PRAGMA optimize")

            busy_timeout = connection.exec_driver_sql("PRAGMA busy_timeout").scalar()
            cache_size = connection.exec_driver_sql("PRAGMA cache_size").scalar()
            mmap_size = connection.exec_driver_sql("PRAGMA mmap_size").scalar()
            temp_store = connection.exec_driver_sql("PRAGMA temp_store").scalar()
            journal_size_limit = connection.exec_driver_sql("PRAGMA journal_size_limit").scalar()
            wal_autocheckpoint = connection.exec_driver_sql("PRAGMA wal_autocheckpoint").scalar()

    diagnostics = {
        "database": "sqlite",
        "journal_mode": str(journal_mode or "").lower(),
        "busy_timeout_ms": int(busy_timeout or 0),
        "cache_size_kib": abs(int(cache_size or 0)),
        "mmap_size_bytes": int(mmap_size or 0),
        "temp_store": int(temp_store or 0),
        "journal_size_limit_bytes": int(journal_size_limit or 0),
        "wal_autocheckpoint_pages": int(wal_autocheckpoint or 0),
    }
    app.logger.info("sqlite_runtime_configured %s", diagnostics)
    return diagnostics
