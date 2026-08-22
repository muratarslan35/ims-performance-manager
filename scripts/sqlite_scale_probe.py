#!/usr/bin/env python
"""Synthetic B-tree scale probe for fifty IMS-sized uploads.

This is intentionally independent from business fixtures: it stresses the three
append-heavy tables at the projected row counts and verifies the exact index
shapes used by production read paths.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
import time
from pathlib import Path


def _plan(connection, sql, params=()):
    return [str(row[3]) for row in connection.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()]


def _bounded(plan, table):
    lowered = [item.lower() for item in plan]
    if any(f"scan {table}" in item and "using index" not in item and "using covering index" not in item for item in lowered):
        return False
    return any("search" in item for item in lowered)


def run_probe(uploads=50, competition_per_upload=100000, raw_per_upload=28091, facts_per_upload=3164, max_query_seconds=3.0):
    with tempfile.TemporaryDirectory(prefix="ims-sqlite-scale-") as temp_name:
        path = Path(temp_name) / "scale.db"
        connection = sqlite3.connect(path)
        try:
            connection.executescript(
                """
                PRAGMA journal_mode=OFF;
                PRAGMA synchronous=OFF;
                PRAGMA temp_store=MEMORY;
                PRAGMA cache_size=-32768;
                CREATE TABLE ims_competition_data (
                    id INTEGER PRIMARY KEY,
                    upload_id INTEGER NOT NULL,
                    metric_type TEXT NOT NULL,
                    is_subtotal INTEGER NOT NULL,
                    is_grand_total INTEGER NOT NULL,
                    subterritory TEXT NOT NULL,
                    product_group TEXT NOT NULL,
                    product_name TEXT NOT NULL,
                    metric_value REAL NOT NULL
                );
                CREATE INDEX ix_competition_upload_metric_flags_subterritory
                    ON ims_competition_data(upload_id, metric_type, is_subtotal, is_grand_total, subterritory);

                CREATE TABLE ims_raw_data (
                    id INTEGER PRIMARY KEY,
                    upload_id INTEGER NOT NULL,
                    sheet_type TEXT,
                    brick TEXT,
                    representative_id INTEGER,
                    product_id INTEGER,
                    unit REAL NOT NULL,
                    tl REAL NOT NULL
                );
                CREATE INDEX ix_ims_raw_upload_sheet_brick
                    ON ims_raw_data(upload_id, sheet_type, brick);

                CREATE TABLE ims_facts (
                    id INTEGER PRIMARY KEY,
                    upload_id INTEGER NOT NULL,
                    representative_id INTEGER,
                    product_id INTEGER NOT NULL,
                    unit REAL NOT NULL,
                    tl REAL NOT NULL
                );
                CREATE INDEX ix_ims_fact_upload_rep_product
                    ON ims_facts(upload_id, representative_id, product_id);
                """
            )

            seed_started = time.perf_counter()
            connection.execute(
                """
                WITH RECURSIVE n(x) AS (
                    VALUES(1) UNION ALL SELECT x + 1 FROM n WHERE x < ?
                )
                INSERT INTO ims_competition_data(
                    upload_id, metric_type, is_subtotal, is_grand_total,
                    subterritory, product_group, product_name, metric_value
                )
                SELECT 1, CASE WHEN x % 2 = 0 THEN 'UNIT' ELSE 'TL' END, 0, 0,
                       printf('BRICK %03d', x % 113),
                       printf('GROUP %02d', x % 7),
                       printf('PRODUCT %03d', x % 80),
                       CAST(x % 5000 AS REAL)
                FROM n
                """,
                (competition_per_upload,),
            )
            connection.execute(
                """
                WITH RECURSIVE n(x) AS (
                    VALUES(1) UNION ALL SELECT x + 1 FROM n WHERE x < ?
                )
                INSERT INTO ims_raw_data(upload_id, sheet_type, brick, representative_id, product_id, unit, tl)
                SELECT 1,
                       CASE WHEN x % 5 = 0 THEN 'dashboard_balance_region' ELSE 'weekly_sales' END,
                       printf('BRICK %03d', x % 113),
                       (x % 113) + 1,
                       (x % 7) + 1,
                       CAST((x % 50) + 1 AS REAL),
                       CAST(((x % 50) + 1) * 100 AS REAL)
                FROM n
                """,
                (raw_per_upload,),
            )
            connection.execute(
                """
                WITH RECURSIVE n(x) AS (
                    VALUES(1) UNION ALL SELECT x + 1 FROM n WHERE x < ?
                )
                INSERT INTO ims_facts(upload_id, representative_id, product_id, unit, tl)
                SELECT 1, (x % 113) + 1, (x % 7) + 1,
                       CAST((x % 50) + 1 AS REAL),
                       CAST(((x % 50) + 1) * 100 AS REAL)
                FROM n
                """,
                (facts_per_upload,),
            )
            connection.commit()

            for upload_id in range(2, uploads + 1):
                connection.execute(
                    """INSERT INTO ims_competition_data(
                           upload_id, metric_type, is_subtotal, is_grand_total,
                           subterritory, product_group, product_name, metric_value)
                       SELECT ?, metric_type, is_subtotal, is_grand_total,
                              subterritory, product_group, product_name, metric_value
                       FROM ims_competition_data WHERE upload_id=1""",
                    (upload_id,),
                )
                connection.execute(
                    """INSERT INTO ims_raw_data(upload_id, sheet_type, brick, representative_id, product_id, unit, tl)
                       SELECT ?, sheet_type, brick, representative_id, product_id, unit, tl
                       FROM ims_raw_data WHERE upload_id=1""",
                    (upload_id,),
                )
                connection.execute(
                    """INSERT INTO ims_facts(upload_id, representative_id, product_id, unit, tl)
                       SELECT ?, representative_id, product_id, unit, tl
                       FROM ims_facts WHERE upload_id=1""",
                    (upload_id,),
                )
                if upload_id % 5 == 0:
                    connection.commit()
            connection.commit()
            seed_seconds = time.perf_counter() - seed_started
            connection.execute("PRAGMA optimize")

            six_uploads = tuple(range(max(1, uploads - 5), uploads + 1))
            placeholders = ",".join("?" for _ in six_uploads)
            queries = {
                "competition_six_uploads": (
                    f"""SELECT product_group, product_name, SUM(metric_value)
                        FROM ims_competition_data
                        WHERE upload_id IN ({placeholders})
                          AND metric_type='UNIT' AND is_subtotal=0 AND is_grand_total=0
                          AND subterritory IN ('BRICK 001','BRICK 002','BRICK 003','BRICK 004','BRICK 005')
                        GROUP BY product_group, product_name""",
                    six_uploads,
                    "ims_competition_data",
                ),
                "raw_latest_brick": (
                    """SELECT SUM(unit), SUM(tl) FROM ims_raw_data
                       WHERE upload_id=? AND sheet_type='weekly_sales' AND brick='BRICK 001'""",
                    (uploads,),
                    "ims_raw_data",
                ),
                "facts_latest_upload": (
                    """SELECT representative_id, product_id, SUM(unit), SUM(tl)
                       FROM ims_facts WHERE upload_id=? GROUP BY representative_id, product_id""",
                    (uploads,),
                    "ims_facts",
                ),
            }

            timings = {}
            plans = {}
            bounded = {}
            for name, (sql, params, table) in queries.items():
                plans[name] = _plan(connection, sql, params)
                bounded[name] = _bounded(plans[name], table)
                started = time.perf_counter()
                connection.execute(sql, params).fetchall()
                timings[name] = round(time.perf_counter() - started, 4)

            counts = {
                "competition": int(connection.execute("SELECT COUNT(*) FROM ims_competition_data").fetchone()[0]),
                "raw": int(connection.execute("SELECT COUNT(*) FROM ims_raw_data").fetchone()[0]),
                "facts": int(connection.execute("SELECT COUNT(*) FROM ims_facts").fetchone()[0]),
            }
            expected = {
                "competition": uploads * competition_per_upload,
                "raw": uploads * raw_per_upload,
                "facts": uploads * facts_per_upload,
            }
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            query_pass = all(value <= max_query_seconds for value in timings.values())
            passed = counts == expected and integrity.lower() == "ok" and all(bounded.values()) and query_pass
            return {
                "result": "PASS" if passed else "FAIL",
                "uploads": uploads,
                "counts": counts,
                "expected": expected,
                "database_bytes": path.stat().st_size,
                "seed_seconds": round(seed_seconds, 3),
                "query_seconds": timings,
                "max_query_seconds": max_query_seconds,
                "bounded_plans": bounded,
                "plans": plans,
                "integrity": integrity,
            }
        finally:
            connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--uploads", type=int, default=50)
    parser.add_argument("--competition-per-upload", type=int, default=100000)
    parser.add_argument("--raw-per-upload", type=int, default=28091)
    parser.add_argument("--facts-per-upload", type=int, default=3164)
    parser.add_argument("--max-query-seconds", type=float, default=3.0)
    args = parser.parse_args()
    result = run_probe(
        uploads=args.uploads,
        competition_per_upload=args.competition_per_upload,
        raw_per_upload=args.raw_per_upload,
        facts_per_upload=args.facts_per_upload,
        max_query_seconds=args.max_query_seconds,
    )
    print("SCALE_PROBE|" + json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if result["result"] == "PASS" else 1)


if __name__ == "__main__":
    main()
