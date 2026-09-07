from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from app import create_app
from app.extensions import db
from app.services.persistent_region_snapshot_service import (
    PersistentRegionSnapshotService,
    region_snapshot_sets,
    region_snapshots,
)
from app.services.persistent_representative_snapshot_service import (
    PersistentRepresentativeSnapshotService,
    representative_snapshot_sets,
    representative_snapshots,
)


def _count(table, condition=None) -> int:
    stmt = db.select(db.func.count()).select_from(table)
    if condition is not None:
        stmt = stmt.where(condition)
    return int(db.session.execute(stmt).scalar_one())


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--database", required=True)
    p.add_argument("--instance-root", required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--month", type=int, required=True)
    p.add_argument("--deleted-upload-id", type=int, required=True)
    p.add_argument("--expected-upload-id", type=int, required=True)
    args = p.parse_args()

    database = Path(args.database).resolve()
    instance_root = Path(args.instance_root).resolve()
    instance_root.mkdir(parents=True, exist_ok=True)

    class Config:
        TESTING = True
        SECRET_KEY = "snapshot-cleanup-rehearsal-only"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False

    app = create_app(Config)
    app.instance_path = str(instance_root)

    with app.app_context():
        region_source = PersistentRegionSnapshotService.source_identity(args.year, args.month)
        rep_source = PersistentRepresentativeSnapshotService.source_identity(args.year, args.month)
        print(f"SNAPSHOT_CLEANUP|SOURCE_BEFORE|region={region_source}|representative={rep_source}")
        assert int(region_source[0]) == args.expected_upload_id
        assert int(rep_source[0]) == args.expected_upload_id

        region_ids = [
            int(row[0])
            for row in db.session.execute(
                db.select(region_snapshot_sets.c.id).where(
                    region_snapshot_sets.c.source_upload_id == args.deleted_upload_id
                )
            ).all()
        ]
        rep_ids = [
            int(row[0])
            for row in db.session.execute(
                db.select(representative_snapshot_sets.c.id).where(
                    representative_snapshot_sets.c.source_upload_id == args.deleted_upload_id
                )
            ).all()
        ]
        region_rows = _count(region_snapshots, region_snapshots.c.set_id.in_(region_ids)) if region_ids else 0
        rep_rows = _count(representative_snapshots, representative_snapshots.c.set_id.in_(rep_ids)) if rep_ids else 0
        print(
            "SNAPSHOT_CLEANUP|STALE_BEFORE|"
            f"region_sets={len(region_ids)}|region_rows={region_rows}|rep_sets={len(rep_ids)}|rep_rows={rep_rows}"
        )

        if region_ids:
            db.session.execute(region_snapshots.delete().where(region_snapshots.c.set_id.in_(region_ids)))
            db.session.execute(region_snapshot_sets.delete().where(region_snapshot_sets.c.id.in_(region_ids)))
        if rep_ids:
            db.session.execute(representative_snapshots.delete().where(representative_snapshots.c.set_id.in_(rep_ids)))
            db.session.execute(representative_snapshot_sets.delete().where(representative_snapshot_sets.c.id.in_(rep_ids)))
        db.session.commit()

        assert _count(region_snapshot_sets, region_snapshot_sets.c.source_upload_id == args.deleted_upload_id) == 0
        assert _count(representative_snapshot_sets, representative_snapshot_sets.c.source_upload_id == args.deleted_upload_id) == 0
        print("SNAPSHOT_CLEANUP|STALE_AFTER|region_sets=0|rep_sets=0")

        region_result = PersistentRegionSnapshotService.build_for_period(args.year, args.month)
        print("SNAPSHOT_CLEANUP|REGION_REBUILD|" + json.dumps(region_result, sort_keys=True, default=str))
        assert region_result.get("status") in {"ACTIVE", "REUSED"}, region_result

        rep_result = PersistentRepresentativeSnapshotService.build_for_period(
            args.year, args.month, force=True
        )
        print("SNAPSHOT_CLEANUP|REP_REBUILD|" + json.dumps(rep_result, sort_keys=True, default=str))
        assert rep_result.get("status") in {"ACTIVE", "REUSED"}, rep_result

        active_region = db.session.execute(
            db.select(region_snapshot_sets.c.id, region_snapshot_sets.c.region_count).where(
                region_snapshot_sets.c.year == args.year,
                region_snapshot_sets.c.month == args.month,
                region_snapshot_sets.c.source_upload_id == args.expected_upload_id,
                region_snapshot_sets.c.status == "ACTIVE",
            ).order_by(region_snapshot_sets.c.id.desc()).limit(1)
        ).first()
        active_rep = db.session.execute(
            db.select(representative_snapshot_sets.c.id, representative_snapshot_sets.c.representative_count).where(
                representative_snapshot_sets.c.year == args.year,
                representative_snapshot_sets.c.month == args.month,
                representative_snapshot_sets.c.source_upload_id == args.expected_upload_id,
                representative_snapshot_sets.c.status == "ACTIVE",
            ).order_by(representative_snapshot_sets.c.id.desc()).limit(1)
        ).first()
        assert active_region is not None
        assert active_rep is not None
        print(
            f"SNAPSHOT_CLEANUP|ACTIVE_WEEK16|region_set={active_region.id}|regions={active_region.region_count}"
            f"|rep_set={active_rep.id}|representatives={active_rep.representative_count}"
        )

    conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=30)
    try:
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        assert not fk, fk[:10]
        assert integrity == "ok", integrity
        print("SNAPSHOT_CLEANUP|DB_CHECK|foreign_keys=ok|integrity=ok")
    finally:
        conn.close()

    print("SNAPSHOT_CLEANUP|PASS")


if __name__ == "__main__":
    main()
