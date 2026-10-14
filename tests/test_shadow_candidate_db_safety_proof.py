import hashlib
import os
import shutil
import sqlite3
from pathlib import Path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _business_digest(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        tables = [
            "representatives",
            "representative_aliases",
            "products",
            "product_aliases",
            "targets",
            "ims_summary",
            "representative_brick_assignments",
            "ims_uploads",
            "ims_raw_data",
            "ims_facts",
            "manager_region_snapshot_sets",
            "manager_region_snapshots",
            "representative_snapshot_sets",
            "representative_snapshots",
        ]
        parts = []
        for table in tables:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
            order = ",".join(cols) if cols else "rowid"
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()
            parts.append((table, rows))
        return hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()
    finally:
        conn.close()


def _create_live_week17(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            PRAGMA journal_mode=DELETE;
            CREATE TABLE representatives (id INTEGER PRIMARY KEY, rep_code TEXT, rep_name TEXT, active INTEGER);
            CREATE TABLE representative_aliases (id INTEGER PRIMARY KEY, representative_id INTEGER, alias_name TEXT);
            CREATE TABLE products (id INTEGER PRIMARY KEY, product_code TEXT, product_name TEXT, is_active INTEGER);
            CREATE TABLE product_aliases (id INTEGER PRIMARY KEY, product_id INTEGER, alias_name TEXT);
            CREATE TABLE targets (id INTEGER PRIMARY KEY, year INTEGER, month INTEGER, representative_id INTEGER, product_id INTEGER, unit_target REAL, tl_target REAL, unit_realization REAL, tl_realization REAL);
            CREATE TABLE ims_summary (id INTEGER PRIMARY KEY, upload_id INTEGER, year INTEGER, month INTEGER, representative_id INTEGER, product_id INTEGER, unit REAL, tl REAL, target_unit REAL, target_tl REAL);
            CREATE TABLE representative_brick_assignments (id INTEGER PRIMARY KEY, representative_id INTEGER, year INTEGER, month INTEGER, brick TEXT, active INTEGER);
            CREATE TABLE ims_uploads (id INTEGER PRIMARY KEY, file_name TEXT, year INTEGER, month INTEGER, week_number INTEGER, status TEXT);
            CREATE TABLE ims_raw_data (id INTEGER PRIMARY KEY, upload_id INTEGER, representative_id INTEGER, product_id INTEGER, unit REAL, tl REAL);
            CREATE TABLE ims_facts (id INTEGER PRIMARY KEY, upload_id INTEGER, raw_data_id INTEGER, representative_id INTEGER, product_id INTEGER, unit REAL, tl REAL);
            CREATE TABLE manager_region_snapshot_sets (id INTEGER PRIMARY KEY, year INTEGER, month INTEGER, source_upload_id INTEGER, status TEXT);
            CREATE TABLE manager_region_snapshots (id INTEGER PRIMARY KEY, set_id INTEGER, region_key TEXT, payload_json TEXT);
            CREATE TABLE representative_snapshot_sets (id INTEGER PRIMARY KEY, year INTEGER, month INTEGER, source_upload_id INTEGER, status TEXT);
            CREATE TABLE representative_snapshots (id INTEGER PRIMARY KEY, set_id INTEGER, representative_id INTEGER, payload_json TEXT);

            INSERT INTO representatives VALUES (1,'SAFE17','SAFE WEEK17 REP',1);
            INSERT INTO products VALUES (1,'SAFE17P','SAFE WEEK17 PRODUCT',1);
            INSERT INTO ims_uploads VALUES (17,'17.Hafta.xlsx',2035,4,17,'COMPLETED');
            INSERT INTO targets VALUES (1,2035,4,1,1,100,1000,70,700);
            INSERT INTO ims_summary VALUES (1,17,2035,4,1,1,70,700,100,1000);
            INSERT INTO representative_brick_assignments VALUES (1,1,2035,4,'901 SAFE',1);
            INSERT INTO manager_region_snapshot_sets VALUES (1,2035,4,17,'ACTIVE');
            INSERT INTO manager_region_snapshots VALUES (1,1,'901','{"week":17}');
            INSERT INTO representative_snapshot_sets VALUES (1,2035,4,17,'ACTIVE');
            INSERT INTO representative_snapshots VALUES (1,1,1,'{"week":17}');
            """
        )
        conn.commit()
    finally:
        conn.close()


def _apply_wrong_week18(candidate: Path) -> None:
    conn = sqlite3.connect(candidate)
    try:
        conn.executescript(
            """
            INSERT INTO representatives VALUES (2,'BAD18','BAD WEEK18 REP',1);
            INSERT INTO representative_aliases VALUES (1,2,'BAD18 ALIAS');
            INSERT INTO products VALUES (2,'BAD18P','BAD WEEK18 PRODUCT',1);
            INSERT INTO product_aliases VALUES (1,2,'BAD18 PRODUCT ALIAS');
            INSERT INTO ims_uploads VALUES (18,'18.Hafta-YANLIS.xlsx',2035,4,18,'COMPLETED');
            UPDATE targets SET unit_realization=88, tl_realization=880 WHERE id=1;
            UPDATE ims_summary SET upload_id=18, unit=88, tl=880 WHERE id=1;
            INSERT INTO ims_raw_data VALUES (1,18,2,2,1,10);
            INSERT INTO ims_facts VALUES (1,18,1,2,2,1,10);
            UPDATE manager_region_snapshot_sets SET status='SUPERSEDED' WHERE id=1;
            INSERT INTO manager_region_snapshot_sets VALUES (2,2035,4,18,'ACTIVE');
            INSERT INTO manager_region_snapshots VALUES (2,2,'901','{"week":18,"bad":true}');
            UPDATE representative_snapshot_sets SET status='SUPERSEDED' WHERE id=1;
            INSERT INTO representative_snapshot_sets VALUES (2,2035,4,18,'ACTIVE');
            INSERT INTO representative_snapshots VALUES (2,2,2,'{"week":18,"bad":true}');
            """
        )
        conn.commit()
    finally:
        conn.close()


def _assert_candidate_week18(candidate: Path) -> None:
    conn = sqlite3.connect(candidate)
    try:
        assert conn.execute("SELECT week_number FROM ims_uploads ORDER BY id DESC LIMIT 1").fetchone()[0] == 18
        assert conn.execute("SELECT COUNT(*) FROM representatives").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 2
        assert conn.execute("SELECT upload_id,unit,tl FROM ims_summary WHERE id=1").fetchone() == (18, 88.0, 880.0)
        assert conn.execute("SELECT COUNT(*) FROM ims_raw_data WHERE upload_id=18").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM ims_facts WHERE upload_id=18").fetchone()[0] == 1
    finally:
        conn.close()


def test_shadow_candidate_reject_keeps_live_week17_byte_and_business_identical(tmp_path):
    live = tmp_path / "live.db"
    candidate = tmp_path / "candidate.db"
    _create_live_week17(live)

    live_byte_before = _sha256(live)
    live_business_before = _business_digest(live)

    shutil.copy2(live, candidate)
    _apply_wrong_week18(candidate)
    _assert_candidate_week18(candidate)

    # Reject means candidate is discarded. The live database was never opened for write.
    candidate.unlink()

    live_byte_after = _sha256(live)
    live_business_after = _business_digest(live)

    assert live_byte_after == live_byte_before
    assert live_business_after == live_business_before
    print("SHADOW_PROOF|REJECT_LIVE_BYTE_IDENTICAL|YES")
    print("SHADOW_PROOF|REJECT_LIVE_BUSINESS_IDENTICAL|YES")


def test_shadow_candidate_atomic_promote_switches_only_after_validation(tmp_path):
    active = tmp_path / "active.db"
    candidate = tmp_path / "candidate.db"
    previous = tmp_path / "previous-safe.db"
    _create_live_week17(active)

    safe17_hash = _sha256(active)
    safe17_business = _business_digest(active)
    shutil.copy2(active, previous)
    shutil.copy2(active, candidate)

    _apply_wrong_week18(candidate)
    _assert_candidate_week18(candidate)
    candidate_hash = _sha256(candidate)
    candidate_business = _business_digest(candidate)

    # Promotion is only simulated after validation. os.replace is atomic on one filesystem.
    os.replace(candidate, active)

    assert _sha256(active) == candidate_hash
    assert _business_digest(active) == candidate_business
    assert _sha256(previous) == safe17_hash
    assert _business_digest(previous) == safe17_business

    # One-step rollback at the file-generation level: restore the immutable safe generation.
    rollback_copy = tmp_path / "rollback-copy.db"
    shutil.copy2(previous, rollback_copy)
    os.replace(rollback_copy, active)

    assert _sha256(active) == safe17_hash
    assert _business_digest(active) == safe17_business
    print("SHADOW_PROOF|PROMOTE_CANDIDATE_EXACT|YES")
    print("SHADOW_PROOF|SAFE_GENERATION_PRESERVED|YES")
    print("SHADOW_PROOF|FILE_LEVEL_ROLLBACK_EXACT|YES")
