#!/usr/bin/env python
"""Audit production SQLite for another ~49 IMS uploads without mutating business data."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
from pathlib import Path


REQUIRED_INDEXES = {
    "ims_competition_data": {"ix_competition_upload_metric_flags_subterritory"},
    "ims_raw_data": {"ix_ims_raw_upload_sheet_brick"},
    "ims_facts": {"ix_ims_fact_upload_rep_product"},
    "ims_summary": {"ix_ims_summary_rep_period_product"},
    "targets": {"ix_target_rep_period_product"},
    "ims_uploads": {"ix_ims_upload_status_period"},
}
LARGE_TABLES = ("ims_competition_data", "ims_raw_data", "ims_facts")


def _scalar(connection, sql, params=()):
    row = connection.execute(sql, params).fetchone()
    return row[0] if row else None


def _index_names(connection, table):
    return {row[1] for row in connection.execute(f"PRAGMA index_list('{table}')").fetchall()}


def _plan(connection, sql, params=()):
    return [str(row[3]) for row in connection.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()]


def _is_bounded_plan(plan, table):
    table_lower = table.lower()
    for item in plan:
        lowered = item.lower()
        if f"scan {table_lower}" in lowered and "using index" not in lowered and "using covering index" not in lowered:
            return False
    return any("search" in item.lower() for item in plan)


def _object_sizes(connection):
    try:
        rows = connection.execute("SELECT name, SUM(pgsize) FROM dbstat GROUP BY name").fetchall()
    except sqlite3.DatabaseError:
        return {}
    return {str(name): int(size or 0) for name, size in rows}


def _table_storage(connection, table, object_sizes):
    if not object_sizes:
        return None
    names = {table}
    names.update(
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?",
            (table,),
        ).fetchall()
        if row[0]
    )
    return sum(object_sizes.get(name, 0) for name in names)


def audit(database_path: Path, additional_uploads: int = 49, optimize: bool = False) -> dict:
    database_path = database_path.resolve()
    connection = sqlite3.connect(database_path, timeout=30)
    connection.execute("PRAGMA busy_timeout=30000")
    try:
        if optimize:
            connection.execute("PRAGMA optimize")

        integrity = str(_scalar(connection, "PRAGMA integrity_check") or "")
        page_size = int(_scalar(connection, "PRAGMA page_size") or 0)
        page_count = int(_scalar(connection, "PRAGMA page_count") or 0)
        freelist_count = int(_scalar(connection, "PRAGMA freelist_count") or 0)
        journal_mode = str(_scalar(connection, "PRAGMA journal_mode") or "").lower()

        latest = connection.execute(
            """
            SELECT id, year, month, week_number, source_record_count, fact_record_count, summary_record_count
            FROM ims_uploads
            WHERE status='COMPLETED'
            ORDER BY year DESC, month DESC, COALESCE(week_number, 0) DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        if not latest:
            raise RuntimeError("No COMPLETED IMS upload found for capacity audit")
        upload_id = int(latest[0])

        current_counts = {
            table: int(_scalar(connection, f"SELECT COUNT(*) FROM {table}") or 0)
            for table in (*LARGE_TABLES, "ims_summary", "targets", "ims_uploads")
        }
        latest_counts = {
            "ims_competition_data": int(
                _scalar(connection, "SELECT COUNT(*) FROM ims_competition_data WHERE upload_id=?", (upload_id,)) or 0
            ),
            "ims_raw_data": int(
                _scalar(connection, "SELECT COUNT(*) FROM ims_raw_data WHERE upload_id=?", (upload_id,)) or 0
            ),
            "ims_facts": int(
                _scalar(connection, "SELECT COUNT(*) FROM ims_facts WHERE upload_id=?", (upload_id,)) or 0
            ),
        }

        index_report = {}
        missing_indexes = []
        for table, required in REQUIRED_INDEXES.items():
            present = _index_names(connection, table)
            missing = sorted(required - present)
            index_report[table] = {"required": sorted(required), "missing": missing}
            missing_indexes.extend(f"{table}:{name}" for name in missing)

        sample_subterritory = _scalar(
            connection,
            "SELECT subterritory FROM ims_competition_data WHERE upload_id=? AND metric_type='UNIT' AND is_subtotal=0 AND is_grand_total=0 LIMIT 1",
            (upload_id,),
        ) or "__CAPACITY_SAMPLE__"
        raw_sample = connection.execute(
            "SELECT sheet_type, brick FROM ims_raw_data WHERE upload_id=? AND brick IS NOT NULL LIMIT 1",
            (upload_id,),
        ).fetchone() or ("weekly_sales", "__CAPACITY_SAMPLE__")
        representative_id = int(
            _scalar(connection, "SELECT representative_id FROM targets WHERE representative_id IS NOT NULL LIMIT 1") or 0
        )

        plans = {
            "competition_scoped": _plan(
                connection,
                """SELECT SUM(metric_value) FROM ims_competition_data
                   WHERE upload_id=? AND metric_type='UNIT' AND is_subtotal=0 AND is_grand_total=0
                     AND subterritory=?""",
                (upload_id, sample_subterritory),
            ),
            "raw_scoped": _plan(
                connection,
                "SELECT SUM(unit), SUM(tl) FROM ims_raw_data WHERE upload_id=? AND sheet_type=? AND brick=?",
                (upload_id, raw_sample[0], raw_sample[1]),
            ),
            "facts_upload": _plan(
                connection,
                "SELECT representative_id, product_id, SUM(unit), SUM(tl) FROM ims_facts WHERE upload_id=? GROUP BY representative_id, product_id",
                (upload_id,),
            ),
            "summary_representative": _plan(
                connection,
                "SELECT product_id, unit, tl FROM ims_summary WHERE representative_id=? AND year=? AND month=?",
                (representative_id, int(latest[1]), int(latest[2])),
            ),
            "target_representative": _plan(
                connection,
                "SELECT product_id, unit_target, tl_target FROM targets WHERE representative_id=? AND year=? AND month=?",
                (representative_id, int(latest[1]), int(latest[2])),
            ),
        }
        bounded = {
            "competition_scoped": _is_bounded_plan(plans["competition_scoped"], "ims_competition_data"),
            "raw_scoped": _is_bounded_plan(plans["raw_scoped"], "ims_raw_data"),
            "facts_upload": _is_bounded_plan(plans["facts_upload"], "ims_facts"),
            "summary_representative": _is_bounded_plan(plans["summary_representative"], "ims_summary"),
            "target_representative": _is_bounded_plan(plans["target_representative"], "targets"),
        }

        object_sizes = _object_sizes(connection)
        storage = {}
        estimated_growth = 0
        for table in LARGE_TABLES:
            table_bytes = _table_storage(connection, table, object_sizes)
            rows = current_counts[table]
            bytes_per_row = (table_bytes / rows) if table_bytes is not None and rows else None
            projected_rows = latest_counts[table] * int(additional_uploads)
            projected_bytes = int(bytes_per_row * projected_rows) if bytes_per_row is not None else None
            if projected_bytes is not None:
                estimated_growth += projected_bytes
            storage[table] = {
                "current_rows": rows,
                "latest_upload_rows": latest_counts[table],
                "table_and_indexes_bytes": table_bytes,
                "bytes_per_row": round(bytes_per_row, 2) if bytes_per_row is not None else None,
                "additional_rows_projected": projected_rows,
                "additional_bytes_projected": projected_bytes,
            }

        disk = shutil.disk_usage(database_path.parent)
        active_bytes = database_path.stat().st_size
        # Retention keeps two IPM rollback copies.  Approximate the extra disk
        # required after all projected imports as three copies of incremental
        # active-DB growth, plus 25% operational safety margin.
        projected_retained_growth = int(estimated_growth * 3 * 1.25) if estimated_growth else None
        storage_status = (
            "PASS"
            if projected_retained_growth is not None and disk.free >= projected_retained_growth
            else "UNKNOWN" if projected_retained_growth is None else "WARNING"
        )

        blocking = []
        if integrity.lower() != "ok":
            blocking.append(f"integrity={integrity}")
        if journal_mode != "wal":
            blocking.append(f"journal_mode={journal_mode}")
        blocking.extend(f"missing_index={item}" for item in missing_indexes)
        blocking.extend(f"unbounded_plan={name}" for name, value in bounded.items() if not value)

        return {
            "result": "PASS" if not blocking else "FAIL",
            "database": str(database_path),
            "integrity": integrity,
            "journal_mode": journal_mode,
            "page_size": page_size,
            "page_count": page_count,
            "freelist_count": freelist_count,
            "freelist_ratio": round(freelist_count / page_count, 6) if page_count else 0.0,
            "active_db_bytes": active_bytes,
            "latest_upload_id": upload_id,
            "additional_uploads_projected": int(additional_uploads),
            "current_counts": current_counts,
            "latest_upload_counts": latest_counts,
            "indexes": index_report,
            "plans": plans,
            "bounded_plans": bounded,
            "storage": storage,
            "estimated_additional_active_bytes": estimated_growth or None,
            "projected_retention_growth_with_safety_bytes": projected_retained_growth,
            "disk_free_bytes": int(disk.free),
            "storage_projection_status": storage_status,
            "blocking": blocking,
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="instance/ipm.db")
    parser.add_argument("--additional-uploads", type=int, default=49)
    parser.add_argument("--optimize", action="store_true")
    args = parser.parse_args()
    payload = audit(Path(args.database), args.additional_uploads, optimize=args.optimize)
    print("DB_CAPACITY|" + json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
