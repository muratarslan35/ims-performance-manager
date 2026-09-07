from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path

from app import create_app
from app.extensions import db
from app.models import IMSImportJob, IMSSummary, IMSUpload, RepresentativeBrickAssignment, Target
from app.services.ims_upload_lifecycle_service import IMSUploadLifecycleService


def _normalize(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _canonical_rows(rows):
    cleaned = []
    for row in rows:
        cleaned.append({key: _normalize(value) for key, value in row.items()})
    return sorted(
        cleaned,
        key=lambda item: json.dumps(
            item, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")
        ),
    )


def _model_rows(model, *, year: int, month: int):
    rows = []
    for row in model.query.filter_by(year=year, month=month).all():
        rows.append({column.name: getattr(row, column.name) for column in model.__table__.columns})
    return _canonical_rows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--upload-root", required=True)
    parser.add_argument("--delete-upload-id", type=int, required=True)
    parser.add_argument("--expected-previous-upload-id", type=int, required=True)
    parser.add_argument("--expected-previous-week", type=int, required=True)
    args = parser.parse_args()

    database = Path(args.database).resolve()
    upload_root = Path(args.upload_root).resolve()
    snapshot_path = upload_root / "ims_archive" / "snapshots" / f"upload-{args.delete_upload_id}.json"
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    year = int(payload["year"])
    month = int(payload["month"])

    class RollbackConfig:
        TESTING = True
        SECRET_KEY = "rollback-rehearsal-only"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = upload_root
        REPORT_FOLDER = upload_root / "reports"
        BACKUP_FOLDER = upload_root / "backups"
        LOG_FOLDER = upload_root / "logs"
        TEMP_FOLDER = upload_root / "temp"
        USER_VAULT_PATH = upload_root / "disabled-user-vault.db"

    app = create_app(RollbackConfig)
    with app.app_context():
        active_jobs = IMSImportJob.query.filter(
            IMSImportJob.status.in_((IMSImportJob.STATUS_QUEUED, IMSImportJob.STATUS_PROCESSING))
        ).count()
        assert active_jobs == 0, active_jobs

        current = db.session.get(IMSUpload, args.delete_upload_id)
        assert current is not None
        allowed, reason = IMSUploadLifecycleService.can_delete(current)
        assert allowed, reason

        result = IMSUploadLifecycleService.delete_upload(args.delete_upload_id)
        assert result["deleted_upload_id"] == args.delete_upload_id
        assert result["restored_previous_period_state"] is True
        assert db.session.get(IMSUpload, args.delete_upload_id) is None

        latest = (
            IMSUpload.query.filter_by(status="COMPLETED")
            .order_by(
                IMSUpload.year.desc(),
                IMSUpload.month.desc(),
                IMSUpload.week_number.desc(),
                IMSUpload.id.desc(),
            )
            .first()
        )
        assert latest is not None
        assert int(latest.id) == args.expected_previous_upload_id
        assert int(latest.week_number) == args.expected_previous_week

        expected_sets = {
            "targets": _canonical_rows(payload.get("targets") or []),
            "summaries": _canonical_rows(payload.get("summaries") or []),
            "brick_assignments": _canonical_rows(payload.get("brick_assignments") or []),
        }
        actual_sets = {
            "targets": _model_rows(Target, year=year, month=month),
            "summaries": _model_rows(IMSSummary, year=year, month=month),
            "brick_assignments": _model_rows(RepresentativeBrickAssignment, year=year, month=month),
        }
        for key in expected_sets:
            assert actual_sets[key] == expected_sets[key], f"{key} snapshot mismatch"
            digest = hashlib.sha256(
                json.dumps(
                    actual_sets[key],
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            print(f"ROLLBACK_REHEARSAL|RESTORED_{key.upper()}|count={len(actual_sets[key])}|sha256={digest}")

        remaining = {}
        for table in db.metadata.sorted_tables:
            for foreign_key in table.foreign_keys:
                if foreign_key.column.table.name != IMSUpload.__tablename__:
                    continue
                if foreign_key.column.name != "id":
                    continue
                column = foreign_key.parent
                count = db.session.execute(
                    db.select(db.func.count()).select_from(table).where(column == args.delete_upload_id)
                ).scalar_one()
                remaining[f"{table.name}.{column.name}"] = int(count)
                assert int(count) == 0, (table.name, column.name, count)
        print("ROLLBACK_REHEARSAL|UPLOAD_CHILDREN|" + json.dumps(remaining, sort_keys=True))

        archived = upload_root / "ims_archive" / f"upload-{args.delete_upload_id}.xlsx"
        deleted_snapshot = upload_root / "ims_archive" / "snapshots" / f"upload-{args.delete_upload_id}.json"
        assert not archived.exists()
        assert not deleted_snapshot.exists()
        print(
            f"ROLLBACK_REHEARSAL|CANDIDATE_LATEST|upload_id={latest.id}|week={latest.week_number}"
        )

    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=30)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        assert integrity == "ok", integrity
        print("ROLLBACK_REHEARSAL|CANDIDATE_INTEGRITY|ok")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
