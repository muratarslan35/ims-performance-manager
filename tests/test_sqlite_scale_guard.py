import sqlite3
from pathlib import Path

from sqlalchemy import create_engine

from app.services.sqlite_import_maintenance import optimize_sqlite_engine
from app.services.sqlite_runtime import (
    CACHE_SIZE_KIB,
    JOURNAL_SIZE_LIMIT_BYTES,
    MMAP_SIZE_BYTES,
    _configure_sqlite_connection,
)
from database_capacity_audit import audit
from scripts.sqlite_scale_probe import run_probe


def test_runtime_applies_bounded_cache_mmap_and_wal_limits(tmp_path):
    path = tmp_path / "runtime.db"
    connection = sqlite3.connect(path)
    try:
        _configure_sqlite_connection(connection, None)
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
        assert connection.execute("PRAGMA cache_size").fetchone()[0] == -CACHE_SIZE_KIB
        assert connection.execute("PRAGMA mmap_size").fetchone()[0] == MMAP_SIZE_BYTES
        assert connection.execute("PRAGMA temp_store").fetchone()[0] == 2  # MEMORY
        assert connection.execute("PRAGMA journal_size_limit").fetchone()[0] == JOURNAL_SIZE_LIMIT_BYTES
    finally:
        connection.close()


def test_post_import_maintenance_is_passive_and_reports_fragmentation(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'maintenance.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        connection.exec_driver_sql("CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)")
        connection.exec_driver_sql("INSERT INTO sample(value) VALUES ('ok')")

    result = optimize_sqlite_engine(engine)

    assert result["result"] == "PASS"
    assert result["database"] == "sqlite"
    assert result["page_count"] > 0
    assert set(result["wal_checkpoint"]) == {"busy", "log_frames", "checkpointed_frames"}


def _make_capacity_db(path: Path):
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE ims_uploads (
                id INTEGER PRIMARY KEY, year INTEGER, month INTEGER, week_number INTEGER,
                source_record_count INTEGER, fact_record_count INTEGER, summary_record_count INTEGER,
                status TEXT
            );
            CREATE INDEX ix_ims_upload_status_period
                ON ims_uploads(status, year, month, week_number, id);
            INSERT INTO ims_uploads VALUES (1, 2026, 1, 5, 10, 2, 1, 'COMPLETED');

            CREATE TABLE ims_competition_data (
                id INTEGER PRIMARY KEY, upload_id INTEGER, metric_type TEXT,
                is_subtotal INTEGER, is_grand_total INTEGER, subterritory TEXT,
                metric_value REAL
            );
            CREATE INDEX ix_competition_upload_metric_flags_subterritory
                ON ims_competition_data(upload_id, metric_type, is_subtotal, is_grand_total, subterritory);
            INSERT INTO ims_competition_data(upload_id,metric_type,is_subtotal,is_grand_total,subterritory,metric_value)
                VALUES (1,'UNIT',0,0,'BRICK 001',10.0);

            CREATE TABLE ims_raw_data (
                id INTEGER PRIMARY KEY, upload_id INTEGER, sheet_type TEXT, brick TEXT,
                unit REAL, tl REAL
            );
            CREATE INDEX ix_ims_raw_upload_sheet_brick
                ON ims_raw_data(upload_id, sheet_type, brick);
            INSERT INTO ims_raw_data(upload_id,sheet_type,brick,unit,tl)
                VALUES (1,'weekly_sales','BRICK 001',1.0,100.0);

            CREATE TABLE ims_facts (
                id INTEGER PRIMARY KEY, upload_id INTEGER, representative_id INTEGER,
                product_id INTEGER, unit REAL, tl REAL
            );
            CREATE INDEX ix_ims_fact_upload_rep_product
                ON ims_facts(upload_id, representative_id, product_id);
            INSERT INTO ims_facts(upload_id,representative_id,product_id,unit,tl)
                VALUES (1,1,1,1.0,100.0);

            CREATE TABLE ims_summary (
                id INTEGER PRIMARY KEY, upload_id INTEGER, representative_id INTEGER,
                product_id INTEGER, year INTEGER, month INTEGER, unit REAL, tl REAL
            );
            CREATE INDEX ix_ims_summary_rep_period_product
                ON ims_summary(representative_id, year, month, product_id);
            INSERT INTO ims_summary(upload_id,representative_id,product_id,year,month,unit,tl)
                VALUES (1,1,1,2026,1,1.0,100.0);

            CREATE TABLE targets (
                id INTEGER PRIMARY KEY, representative_id INTEGER, product_id INTEGER,
                year INTEGER, month INTEGER, unit_target REAL, tl_target REAL
            );
            CREATE INDEX ix_target_rep_period_product
                ON targets(representative_id, year, month, product_id);
            INSERT INTO targets(representative_id,product_id,year,month,unit_target,tl_target)
                VALUES (1,1,2026,1,1.0,100.0);

            -- Keep the synthetic database large enough for EXPLAIN to exercise
            -- the production access path after PRAGMA optimize has populated
            -- sqlite_stat1.  Newer SQLite versions correctly prefer a table
            -- scan for a one-row table, which is not evidence about the
            -- projected multi-upload database this guard is intended to test.
            -- Historical upload_id=0 rows preserve the latest-upload assertions.
            WITH RECURSIVE seq(n) AS (
                VALUES (2) UNION ALL SELECT n + 1 FROM seq WHERE n <= 256
            )
            INSERT INTO ims_competition_data(
                upload_id,metric_type,is_subtotal,is_grand_total,subterritory,metric_value
            ) SELECT 0,'UNIT',0,0,printf('HISTORIC BRICK %04d', n),1.0 FROM seq;

            WITH RECURSIVE seq(n) AS (
                VALUES (2) UNION ALL SELECT n + 1 FROM seq WHERE n <= 256
            )
            INSERT INTO ims_raw_data(upload_id,sheet_type,brick,unit,tl)
                SELECT 0,'weekly_sales',printf('HISTORIC BRICK %04d', n),1.0,1.0 FROM seq;

            WITH RECURSIVE seq(n) AS (
                VALUES (2) UNION ALL SELECT n + 1 FROM seq WHERE n <= 256
            )
            INSERT INTO ims_facts(upload_id,representative_id,product_id,unit,tl)
                SELECT 0,n,n,1.0,1.0 FROM seq;

            WITH RECURSIVE seq(n) AS (
                VALUES (2) UNION ALL SELECT n + 1 FROM seq WHERE n <= 256
            )
            INSERT INTO ims_summary(upload_id,representative_id,product_id,year,month,unit,tl)
                SELECT 0,n,n,2025,12,1.0,1.0 FROM seq;

            WITH RECURSIVE seq(n) AS (
                VALUES (2) UNION ALL SELECT n + 1 FROM seq WHERE n <= 256
            )
            INSERT INTO targets(representative_id,product_id,year,month,unit_target,tl_target)
                SELECT n,n,2025,12,1.0,1.0 FROM seq;
            """
        )
        connection.commit()
    finally:
        connection.close()


def test_capacity_audit_projects_49_uploads_and_rejects_full_scans(tmp_path):
    path = tmp_path / "capacity.db"
    _make_capacity_db(path)

    result = audit(path, additional_uploads=49, optimize=True)

    assert result["result"] == "PASS"
    assert result["additional_uploads_projected"] == 49
    assert result["latest_upload_counts"]["ims_competition_data"] == 1
    assert all(result["bounded_plans"].values())
    assert not result["blocking"]


def test_scale_probe_keeps_latest_reads_index_bounded():
    result = run_probe(
        uploads=5,
        competition_per_upload=1000,
        raw_per_upload=300,
        facts_per_upload=100,
        max_query_seconds=1.0,
    )

    assert result["result"] == "PASS"
    assert result["counts"]["competition"] == 5000
    assert all(result["bounded_plans"].values())
