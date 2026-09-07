from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

SHARED_TABLES = [
    "representatives",
    "products",
    "representative_aliases",
    "product_aliases",
    "manager_region_snapshot_sets",
    "manager_region_snapshot_rows",
    "representative_snapshot_sets",
    "representative_snapshot_rows",
]


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f"PRAGMA table_info({qident(table)})")]


def rows(conn: sqlite3.Connection, table: str) -> list[dict]:
    cur = conn.execute(f"SELECT * FROM {qident(table)}")
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def digest(data: list[dict]) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def find_upload_table(conn: sqlite3.Connection) -> str:
    for name in ("ims_uploads", "ims_upload"):
        if table_exists(conn, name):
            return name
    raise RuntimeError("IMS upload table not found")


def upload_row(conn: sqlite3.Connection, upload_id: int) -> dict:
    table = find_upload_table(conn)
    cur = conn.execute(f"SELECT * FROM {qident(table)} WHERE id=?", (upload_id,))
    names = [d[0] for d in cur.description]
    row = cur.fetchone()
    if row is None:
        return {}
    return dict(zip(names, row))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--previous-upload-id", type=int, required=True)
    p.add_argument("--deleted-upload-id", type=int, required=True)
    args = p.parse_args()

    base = sqlite3.connect(f"file:{Path(args.baseline).resolve()}?mode=ro", uri=True, timeout=30)
    cand = sqlite3.connect(f"file:{Path(args.candidate).resolve()}?mode=ro", uri=True, timeout=30)
    try:
        u31 = upload_row(base, args.previous_upload_id)
        u32 = upload_row(base, args.deleted_upload_id)
        print("SHARED_RESIDUE|UPLOAD_PREVIOUS|" + json.dumps(u31, ensure_ascii=False, sort_keys=True, default=str))
        print("SHARED_RESIDUE|UPLOAD_DELETED|" + json.dumps(u32, ensure_ascii=False, sort_keys=True, default=str))

        for table in SHARED_TABLES:
            if not table_exists(base, table) or not table_exists(cand, table):
                print(f"SHARED_RESIDUE|TABLE_MISSING|table={table}")
                continue
            bcols = columns(base, table)
            brows = rows(base, table)
            crows = rows(cand, table)
            same = brows == crows
            print(
                f"SHARED_RESIDUE|TABLE|table={table}|baseline_count={len(brows)}|candidate_count={len(crows)}"
                f"|same_after_rollback={str(same).lower()}|baseline_sha={digest(brows)}|candidate_sha={digest(crows)}"
            )

            upload_cols = [c for c in bcols if c in {"upload_id", "source_upload_id", "ims_upload_id", "latest_upload_id"}]
            for col in upload_cols:
                count = cand.execute(
                    f"SELECT COUNT(*) FROM {qident(table)} WHERE {qident(col)}=?", (args.deleted_upload_id,)
                ).fetchone()[0]
                print(f"SHARED_RESIDUE|UPLOAD32_REF|table={table}|column={col}|count={int(count)}")

            time_cols = [
                c for c in bcols
                if c in {"created_at", "updated_at", "generated_at", "built_at", "published_at", "completed_at", "created_on", "updated_on"}
            ]
            print(
                "SHARED_RESIDUE|SCHEMA|table=" + table
                + "|time_cols=" + ",".join(time_cols)
                + "|columns=" + ",".join(bcols)
            )
            for col in time_cols:
                sample = cand.execute(
                    f"SELECT * FROM {qident(table)} WHERE {qident(col)} IS NOT NULL ORDER BY {qident(col)} DESC LIMIT 5"
                ).fetchall()
                if sample:
                    print(
                        f"SHARED_RESIDUE|RECENT_SAMPLE|table={table}|column={col}|rows="
                        + json.dumps([list(r) for r in sample], ensure_ascii=False, default=str)
                    )

        integrity = cand.execute("PRAGMA integrity_check").fetchone()[0]
        print(f"SHARED_RESIDUE|CANDIDATE_INTEGRITY|{integrity}")
        assert integrity == "ok"
        print("SHARED_RESIDUE|AUDIT|PASS")
    finally:
        base.close()
        cand.close()


if __name__ == "__main__":
    main()
