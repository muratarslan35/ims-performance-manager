"""Low-impact SQLite maintenance after successful IMS imports.

The IMS database is append-heavy.  Full VACUUM would block readers and rewrite the
whole database, so production maintenance is deliberately limited to SQLite's
incremental optimizer plus a PASSIVE WAL checkpoint.  Both operations are safe to
run while normal read traffic continues.
"""
from __future__ import annotations

import logging
from functools import wraps

from app.extensions import db

logger = logging.getLogger(__name__)


def optimize_sqlite_engine(engine) -> dict:
    """Refresh planner statistics and checkpoint WAL without blocking readers."""
    if engine.dialect.name != "sqlite":
        return {"database": engine.dialect.name, "result": "SKIPPED"}

    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        try:
            cursor.execute("PRAGMA optimize")
            optimize_rows = cursor.fetchall()
            cursor.execute("PRAGMA wal_checkpoint(PASSIVE)")
            checkpoint = cursor.fetchone() or (0, 0, 0)
            cursor.execute("PRAGMA page_count")
            page_count = int((cursor.fetchone() or (0,))[0] or 0)
            cursor.execute("PRAGMA freelist_count")
            freelist_count = int((cursor.fetchone() or (0,))[0] or 0)
        finally:
            cursor.close()
    finally:
        raw.close()

    result = {
        "database": "sqlite",
        "result": "PASS",
        "wal_checkpoint": {
            "busy": int(checkpoint[0] or 0),
            "log_frames": int(checkpoint[1] or 0),
            "checkpointed_frames": int(checkpoint[2] or 0),
        },
        "page_count": page_count,
        "freelist_count": freelist_count,
        "freelist_ratio": round(freelist_count / page_count, 6) if page_count else 0.0,
        "optimize_rows": len(optimize_rows),
    }
    return result


def safe_post_import_maintenance() -> dict:
    """Never turn a committed IMS import into a false failure because of maintenance."""
    try:
        result = optimize_sqlite_engine(db.engine)
        logger.info("sqlite_post_import_maintenance %s", result)
        return result
    except Exception as exc:  # maintenance is advisory after the atomic commit
        logger.warning("sqlite_post_import_maintenance_failed %s", exc, exc_info=True)
        return {"database": "sqlite", "result": "WARNING", "error": str(exc)}


def install_sqlite_import_maintenance() -> None:
    """Attach maintenance outside the canonical atomic IMS import transaction."""
    from app.services.ims_import_service import IMSImportService

    current = IMSImportService.run
    if getattr(current, "_sqlite_maintenance_wrapper", False):
        return

    @wraps(current)
    def wrapped(self, *args, **kwargs):
        report = current(self, *args, **kwargs)
        if report.get("success"):
            report["sqlite_maintenance"] = safe_post_import_maintenance()
        return report

    wrapped._sqlite_maintenance_wrapper = True
    IMSImportService.run = wrapped
