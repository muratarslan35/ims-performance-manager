"""Safe lifecycle management for imported IMS workbooks.

The service deliberately separates three concerns:

* hide/show only controls the IMS history UI and never changes calculations;
* exact duplicate detection uses the queue's SHA-256 source hash;
* physical deletion is allowed only when the current period state can be restored.

Weekly raw/fact/competition history is upload-scoped, while Target, IMSSummary and
RepresentativeBrickAssignment are period-scoped current-state tables. Before a
new import is published we therefore persist a compact rollback snapshot of only
those three period-scoped tables. Deleting the latest upload restores that
snapshot and then removes rows directly owned by the deleted IMSUpload.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

from flask import current_app
from sqlalchemy import DateTime, MetaData, Table, inspect

from app.extensions import db
from app.models import (
    IMSImportJob,
    IMSSummary,
    IMSUpload,
    RepresentativeBrickAssignment,
    Setting,
    Target,
)


class IMSUploadLifecycleService:
    HIDDEN_KEY_PREFIX = "IMS_UPLOAD_HIDDEN_"
    SNAPSHOT_VERSION = 1

    @classmethod
    def _archive_root(cls) -> Path:
        root = Path(current_app.config["UPLOAD_FOLDER"]) / "ims_archive"
        root.mkdir(parents=True, exist_ok=True)
        return root

    @classmethod
    def _snapshot_root(cls) -> Path:
        root = cls._archive_root() / "snapshots"
        root.mkdir(parents=True, exist_ok=True)
        return root

    @classmethod
    def pending_snapshot_path(cls, job_id: int) -> Path:
        return cls._snapshot_root() / f"job-{int(job_id)}.json"

    @classmethod
    def upload_snapshot_path(cls, upload_id: int) -> Path:
        return cls._snapshot_root() / f"upload-{int(upload_id)}.json"

    @classmethod
    def archived_source_path(cls, upload_id: int, suffix: str = ".xlsx") -> Path:
        safe_suffix = suffix.lower() if suffix.lower() in {".xlsx", ".xls"} else ".xlsx"
        return cls._archive_root() / f"upload-{int(upload_id)}{safe_suffix}"

    @staticmethod
    def _serialize_rows(rows: Iterable[object], excluded: set[str] | None = None) -> list[dict]:
        excluded = excluded or set()
        result = []
        for row in rows:
            values = {}
            for column in row.__table__.columns:
                if column.name in excluded:
                    continue
                value = getattr(row, column.name)
                if hasattr(value, "isoformat"):
                    value = value.isoformat()
                values[column.name] = value
            result.append(values)
        return result

    @classmethod
    def capture_period_snapshot(cls, *, job_id: int, year: int, month: int) -> Path:
        """Persist the state that must be restored if the next import is removed."""
        payload = {
            "version": cls.SNAPSHOT_VERSION,
            "year": int(year),
            "month": int(month),
            "targets": cls._serialize_rows(
                Target.query.filter_by(year=int(year), month=int(month)).all(),
                excluded={"id", "created_at"},
            ),
            "summaries": cls._serialize_rows(
                IMSSummary.query.filter_by(year=int(year), month=int(month)).all(),
                excluded={"id", "created_at"},
            ),
            "brick_assignments": cls._serialize_rows(
                RepresentativeBrickAssignment.query.filter_by(year=int(year), month=int(month)).all(),
                excluded={"id", "created_at", "updated_at"},
            ),
        }
        path = cls.pending_snapshot_path(job_id)
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        return path

    @classmethod
    def discard_pending_snapshot(cls, job_id: int) -> None:
        cls.pending_snapshot_path(job_id).unlink(missing_ok=True)

    @classmethod
    def finalize_snapshot(cls, *, job_id: int, upload_id: int) -> Path | None:
        source = cls.pending_snapshot_path(job_id)
        if not source.exists():
            return None
        destination = cls.upload_snapshot_path(upload_id)
        source.replace(destination)
        return destination

    @classmethod
    def archive_successful_source(cls, *, staging_path: Path, upload_id: int) -> Path:
        destination = cls.archived_source_path(upload_id, staging_path.suffix)
        destination.write_bytes(staging_path.read_bytes())
        return destination

    @classmethod
    def exact_duplicate_job(cls, source_hash: str) -> IMSImportJob | None:
        return (
            IMSImportJob.query
            .join(IMSUpload, IMSImportJob.ims_upload_id == IMSUpload.id)
            .filter(
                IMSImportJob.source_hash == str(source_hash),
                IMSImportJob.status == IMSImportJob.STATUS_COMPLETED,
                IMSUpload.status == "COMPLETED",
            )
            .order_by(IMSImportJob.completed_at.desc(), IMSImportJob.id.desc())
            .first()
        )

    @classmethod
    def existing_week_job(cls, *, year: int, month: int, week_number: int | None) -> IMSImportJob | None:
        if week_number is None:
            return None
        return (
            IMSImportJob.query
            .join(IMSUpload, IMSImportJob.ims_upload_id == IMSUpload.id)
            .filter(
                IMSImportJob.year == int(year),
                IMSImportJob.month == int(month),
                IMSImportJob.status == IMSImportJob.STATUS_COMPLETED,
                IMSUpload.status == "COMPLETED",
                IMSUpload.week_number == int(week_number),
            )
            .order_by(IMSUpload.completed_at.desc(), IMSUpload.id.desc())
            .first()
        )

    @classmethod
    def hidden_setting_key(cls, upload_id: int) -> str:
        return f"{cls.HIDDEN_KEY_PREFIX}{int(upload_id)}"

    @classmethod
    def hidden_upload_ids(cls) -> set[int]:
        rows = Setting.query.filter(Setting.setting_key.like(f"{cls.HIDDEN_KEY_PREFIX}%")).all()
        hidden = set()
        for row in rows:
            try:
                hidden.add(int(row.setting_key[len(cls.HIDDEN_KEY_PREFIX):]))
            except (TypeError, ValueError):
                continue
        return hidden

    @classmethod
    def set_hidden(cls, upload_id: int, hidden: bool) -> None:
        key = cls.hidden_setting_key(upload_id)
        row = Setting.query.filter_by(setting_key=key).first()
        if hidden:
            if row is None:
                db.session.add(Setting(
                    setting_key=key,
                    setting_value="1",
                    category="IMS",
                    description="IMS geçmiş listesinde gizlenen yükleme",
                ))
        elif row is not None:
            db.session.delete(row)
        db.session.commit()

    @classmethod
    def _latest_completed_for_period(cls, upload: IMSUpload) -> IMSUpload | None:
        return (
            IMSUpload.query
            .filter_by(year=upload.year, month=upload.month, status="COMPLETED")
            .order_by(IMSUpload.week_number.desc(), IMSUpload.completed_at.desc(), IMSUpload.id.desc())
            .first()
        )

    @classmethod
    def can_delete(cls, upload: IMSUpload) -> tuple[bool, str]:
        if upload.status != "COMPLETED":
            return True, ""
        latest = cls._latest_completed_for_period(upload)
        if latest is None or latest.id != upload.id:
            return True, ""
        if cls.upload_snapshot_path(upload.id).exists():
            return True, ""
        return False, "Bu eski IMS için geri dönüş snapshot'ı yok; aktif dönem güvenle geri alınamaz."

    @staticmethod
    def _restore_rows(model, rows: list[dict]) -> None:
        columns = {column.name: column for column in model.__table__.columns}
        for values in rows:
            clean = {}
            for key, value in values.items():
                column = columns.get(key)
                if column is None:
                    continue
                if value is not None and isinstance(column.type, DateTime) and isinstance(value, str):
                    value = datetime.fromisoformat(value)
                clean[key] = value
            db.session.add(model(**clean))

    @classmethod
    def _restore_period_snapshot(cls, upload: IMSUpload) -> None:
        path = cls.upload_snapshot_path(upload.id)
        if not path.exists():
            raise RuntimeError("Silme için gerekli geri dönüş snapshot'ı bulunamadı.")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("version", 0)) != cls.SNAPSHOT_VERSION:
            raise RuntimeError("Geri dönüş snapshot sürümü desteklenmiyor.")
        if (int(payload.get("year", 0)), int(payload.get("month", 0))) != (upload.year, upload.month):
            raise RuntimeError("Geri dönüş snapshot dönemi IMS dönemiyle eşleşmiyor.")

        Target.query.filter_by(year=upload.year, month=upload.month).delete(synchronize_session=False)
        IMSSummary.query.filter_by(year=upload.year, month=upload.month).delete(synchronize_session=False)
        RepresentativeBrickAssignment.query.filter_by(
            year=upload.year, month=upload.month
        ).delete(synchronize_session=False)
        db.session.flush()

        cls._restore_rows(Target, payload.get("targets") or [])
        cls._restore_rows(IMSSummary, payload.get("summaries") or [])
        cls._restore_rows(RepresentativeBrickAssignment, payload.get("brick_assignments") or [])
        db.session.flush()

    @classmethod
    def _delete_direct_upload_children(cls, upload_id: int) -> None:
        """Delete every table row whose FK points directly to ims_uploads.id."""
        inspector = inspect(db.engine)
        metadata = MetaData()
        child_tables = []
        for table_name in inspector.get_table_names():
            if table_name == "ims_uploads":
                continue
            for foreign_key in inspector.get_foreign_keys(table_name):
                if foreign_key.get("referred_table") != "ims_uploads":
                    continue
                constrained = foreign_key.get("constrained_columns") or []
                referred = foreign_key.get("referred_columns") or []
                if constrained == ["upload_id"] and referred == ["id"]:
                    child_tables.append(table_name)
                    break
                if constrained == ["ims_upload_id"] and referred == ["id"]:
                    child_tables.append(table_name)
                    break

        for table_name in child_tables:
            table = Table(table_name, metadata, autoload_with=db.engine)
            column = table.c.get("upload_id")
            if column is None:
                column = table.c.get("ims_upload_id")
            if column is not None:
                db.session.execute(table.delete().where(column == int(upload_id)))

    @classmethod
    def delete_upload(cls, upload_id: int) -> dict:
        active = IMSImportJob.query.filter(
            IMSImportJob.status.in_((IMSImportJob.STATUS_QUEUED, IMSImportJob.STATUS_PROCESSING))
        ).first()
        if active is not None:
            raise RuntimeError("Aktif IMS importu varken silme yapılamaz.")

        upload = db.session.get(IMSUpload, int(upload_id))
        if upload is None:
            raise LookupError("IMS yüklemesi bulunamadı.")
        allowed, reason = cls.can_delete(upload)
        if not allowed:
            raise RuntimeError(reason)

        deleted_upload_id = int(upload.id)
        hidden_key = cls.hidden_setting_key(deleted_upload_id)
        hidden = Setting.query.filter_by(setting_key=hidden_key).first()
        latest = cls._latest_completed_for_period(upload) if upload.status == "COMPLETED" else None
        restored = bool(latest is not None and latest.id == deleted_upload_id)
        try:
            if restored:
                cls._restore_period_snapshot(upload)

            # Use Core deletes for upload-owned rows and the parent upload. ORM
            # relationship synchronization can otherwise try to NULL non-nullable
            # child FKs when a child object happens to already be present in the
            # current identity map. The explicit SQL order is deterministic and
            # remains inside the same transaction.
            cls._delete_direct_upload_children(deleted_upload_id)
            if hidden is not None:
                db.session.delete(hidden)
            db.session.execute(
                IMSUpload.__table__.delete().where(IMSUpload.id == deleted_upload_id)
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        for suffix in (".xlsx", ".xls"):
            cls.archived_source_path(deleted_upload_id, suffix).unlink(missing_ok=True)
        cls.upload_snapshot_path(deleted_upload_id).unlink(missing_ok=True)
        return {"deleted_upload_id": deleted_upload_id, "restored_previous_period_state": restored}
