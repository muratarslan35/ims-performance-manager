"""SQLite runtime hardening for a single-server IMS deployment.

The IMS import pipeline intentionally commits atomically.  SQLite therefore has
one long-lived writer while a workbook is being finalized.  WAL mode lets normal
application reads continue during that writer, while busy_timeout gives short
competing writes a bounded wait instead of an immediate ``database is locked``.
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


def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA wal_autocheckpoint=1000")
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

    ``journal_mode=WAL`` is persistent in the database file.  We still execute
    the statement at startup so a restored/copied database is automatically
    brought back to the expected production mode before writable traffic.
    """
    uri = str(app.config.get("SQLALCHEMY_DATABASE_URI", ""))
    if not uri.startswith("sqlite:"):
        return {"database": "non-sqlite", "journal_mode": None, "busy_timeout_ms": None}

    with app.app_context():
        with db.engine.connect() as connection:
            journal_mode = connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar()
            connection.exec_driver_sql(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            connection.exec_driver_sql("PRAGMA synchronous=NORMAL")
            connection.exec_driver_sql("PRAGMA wal_autocheckpoint=1000")
            busy_timeout = connection.exec_driver_sql("PRAGMA busy_timeout").scalar()

    diagnostics = {
        "database": "sqlite",
        "journal_mode": str(journal_mode or "").lower(),
        "busy_timeout_ms": int(busy_timeout or 0),
    }
    app.logger.info("sqlite_runtime_configured %s", diagnostics)
    return diagnostics
