"""Safe lifecycle management for imported IMS workbooks.

The service deliberately separates three concerns:

* hide/show only controls the IMS history UI and never changes calculations;
* duplicate detection first uses source SHA-256 and, when an archived source is
  available, also compares workbook cell data while ignoring formatting/metadata;
* physical deletion is allowed only when the current period state can be restored.

Weekly raw/fact/competition history is upload-scoped, while Target, IMSSummary and
RepresentativeBrickAssignment are period-scoped current-state tables. Before a
new import is published we persist an exact rollback snapshot of those three
period-scoped tables. Deleting the latest upload removes the newer upload-owned
rows first and restores the previous current-state snapshot as the final write.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from flask import current_app
import sqlalchemy as sa
from sqlalchemy import DateTime, desc

from app.extensions import db
from app.models import (
    AuditLog,
    IMSImportJob,
    IMSSummary,
    IMSUpload,
    Product,
    Representative,
    RepresentativeBrickAssignment,
    Setting,
    Target,
)


class IMSUploadLifecycleService:
    HIDDEN_KEY_PREFIX = "IMS_UPLOAD_HIDDEN_"
    SNAPSHOT_VERSION = 3
    SUPPORTED_SNAPSHOT_VERSIONS = (2, 3)
    READABLE_UPLOAD_STATUSES = (IMSUpload.STATUS_COMPLETED, IMSUpload.STATUS_ROLLED_BACK)

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

    @classmethod
    def archived_source_for_upload(cls, upload_id: int) -> Path | None:
        for suffix in (".xlsx", ".xls"):
            candidate = cls.archived_source_path(upload_id, suffix)
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def _validate_archived_source(cls, upload_id: int) -> Path:
        path = cls.archived_source_for_upload(upload_id)
        if path is None:
            raise RuntimeError("Önceki IMS'in arşiv kaynak dosyası bulunamadı.")
        job = IMSImportJob.query.filter_by(
            ims_upload_id=int(upload_id),
            status=IMSImportJob.STATUS_COMPLETED,
        ).order_by(IMSImportJob.completed_at.desc(), IMSImportJob.id.desc()).first()
        if job is None or not str(job.source_hash or "").strip():
            raise RuntimeError("Önceki IMS arşiv kaynağının kayıtlı SHA-256 kimliği yok.")
        if cls._file_sha256(path) != str(job.source_hash).strip().lower():
            raise RuntimeError("Önceki IMS arşiv dosyası SHA-256 kimliğiyle eşleşmiyor.")
        return path

    @staticmethod
    def _semantic_cell(value):
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Decimal):
            value = float(value)
        if isinstance(value, float):
            if value != value:
                return None
            if value == 0:
                return 0
            return format(value, ".15g")
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str):
            return value.strip()
        return str(value).strip()

    @classmethod
    def semantic_workbook_hash(cls, file_path: Path) -> str | None:
        """Hash workbook sheet/cell values while ignoring workbook formatting."""
        path = Path(file_path)
        if path.suffix.lower() != ".xlsx" or not path.is_file():
            return None
        try:
            from openpyxl import load_workbook

            workbook = load_workbook(path, read_only=True, data_only=False)
            digest = hashlib.sha256()
            try:
                for sheet in workbook.worksheets:
                    digest.update(b"S\0")
                    digest.update(str(sheet.title).strip().encode("utf-8"))
                    digest.update(b"\0")
                    last_nonempty_row = 0
                    buffered_rows = []
                    for row_index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                        normalized = [cls._semantic_cell(value) for value in row]
                        while normalized and normalized[-1] is None:
                            normalized.pop()
                        if normalized:
                            last_nonempty_row = row_index
                        buffered_rows.append((row_index, normalized))
                    for row_index, normalized in buffered_rows:
                        if row_index > last_nonempty_row:
                            break
                        digest.update(b"R\0")
                        digest.update(str(row_index).encode("ascii"))
                        digest.update(b"\0")
                        digest.update(
                            json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                        )
                        digest.update(b"\0")
            finally:
                workbook.close()
            return digest.hexdigest()
        except Exception:
            current_app.logger.exception("ims_semantic_fingerprint_failed file=%s", path.name)
            return None

    @classmethod
    def same_semantic_workbook(cls, new_path: Path, existing_upload_id: int) -> bool | None:
        archived = cls.archived_source_for_upload(existing_upload_id)
        if archived is None:
            return None
        new_hash = cls.semantic_workbook_hash(new_path)
        old_hash = cls.semantic_workbook_hash(archived)
        if new_hash is None or old_hash is None:
            return None
        return new_hash == old_hash

    @staticmethod
    def _serialize_rows(rows: Iterable[object]) -> list[dict]:
        result = []
        for row in rows:
            values = {}
            for column in row.__table__.columns:
                value = getattr(row, column.name)
                if hasattr(value, "isoformat"):
                    value = value.isoformat()
                values[column.name] = value
            result.append(values)
        return result

    @classmethod
    def _master_state(cls) -> dict:
        return {
            "representatives": cls._serialize_rows(Representative.query.order_by(Representative.id).all()),
            "products": cls._serialize_rows(Product.query.order_by(Product.id).all()),
        }

    @staticmethod
    def _write_snapshot_payload(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".json.tmp-{os.getpid()}")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    @classmethod
    def capture_period_snapshot(cls, *, job_id: int, year: int, month: int) -> Path:
        """Persist the exact current-state rows before a new IMS replaces them."""
        from app.services.persistent_dashboard_snapshot_service import (
            PersistentDashboardSnapshotService,
        )

        _ims_id, production_id = PersistentDashboardSnapshotService.source_identity(year, month)
        payload = {
            "version": cls.SNAPSHOT_VERSION,
            "year": int(year),
            "month": int(month),
            "source_upload_id": db.session.query(IMSUpload.id).filter(
                IMSUpload.year == int(year),
                IMSUpload.month == int(month),
                IMSUpload.status == IMSUpload.STATUS_COMPLETED,
            ).order_by(
                desc(IMSUpload.week_number), desc(IMSUpload.completed_at), desc(IMSUpload.id)
            ).limit(1).scalar(),
            "dashboard_production_upload_id": int(production_id),
            "targets": cls._serialize_rows(
                Target.query.filter_by(year=int(year), month=int(month)).all()
            ),
            "summaries": cls._serialize_rows(
                IMSSummary.query.filter_by(year=int(year), month=int(month)).all()
            ),
            "brick_assignments": cls._serialize_rows(
                RepresentativeBrickAssignment.query.filter_by(year=int(year), month=int(month)).all()
            ),
            "master_before": cls._master_state(),
        }
        path = cls.pending_snapshot_path(job_id)
        cls._write_snapshot_payload(path, payload)
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
    def seal_snapshot_master_state(cls, *, upload_id: int) -> Path:
        """Record the exact post-import master state after roster synchronization."""
        path = cls.upload_snapshot_path(upload_id)
        if not path.is_file():
            raise RuntimeError("IMS rollback snapshot'ı finalize edilmedi.")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("version", 0)) != cls.SNAPSHOT_VERSION:
            raise RuntimeError("IMS rollback snapshot sürümü master günlüğünü desteklemiyor.")
        payload["master_after"] = cls._master_state()
        payload["sealed_upload_id"] = int(upload_id)
        payload["sealed_at"] = datetime.utcnow().isoformat()
        cls._write_snapshot_payload(path, payload)
        return path

    @classmethod
    def prepare_previous_rollback_assets(cls, *, year: int, month: int) -> dict:
        """Guarantee all immutable read models before replacement data can mutate."""
        previous = IMSUpload.query.filter_by(
            year=int(year), month=int(month), status=IMSUpload.STATUS_COMPLETED
        ).order_by(
            desc(IMSUpload.week_number), desc(IMSUpload.completed_at), desc(IMSUpload.id)
        ).first()
        if previous is None:
            return {"status": "FIRST_UPLOAD", "source_upload_id": 0}

        cls._validate_archived_source(previous.id)

        from app.services.dashboard_service import DashboardService
        from app.services.persistent_dashboard_snapshot_service import (
            PersistentDashboardSnapshotService,
        )
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

        ims_id, production_id = PersistentDashboardSnapshotService.source_identity(year, month)
        if int(ims_id) != int(previous.id):
            raise RuntimeError("Aktif IMS kimliği rollback hazırlığı sırasında değişti.")
        PersistentDashboardSnapshotService.get_or_build(
            year,
            month,
            lambda: DashboardService(year=year, month=month).run(),
        )
        if not PersistentDashboardSnapshotService.generation_ready(
            year, month, previous.id, production_id
        ):
            raise RuntimeError("Önceki IMS dashboard snapshot nesli hazırlanamadı.")

        PersistentRegionSnapshotService.build_for_period(year, month)
        PersistentRepresentativeSnapshotService.build_for_period(year, month)
        region_set_id = cls._snapshot_set_for_source(
            region_snapshot_sets,
            region_snapshots,
            region_snapshot_sets.c.region_count,
            upload=previous,
            source_id=previous.id,
        )
        representative_set_id = cls._snapshot_set_for_source(
            representative_snapshot_sets,
            representative_snapshots,
            representative_snapshot_sets.c.representative_count,
            upload=previous,
            source_id=previous.id,
        )
        return {
            "status": "READY",
            "source_upload_id": int(previous.id),
            "production_upload_id": int(production_id),
            "region_snapshot_set_id": region_set_id,
            "representative_snapshot_set_id": representative_set_id,
        }

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
                IMSUpload.status.in_(cls.READABLE_UPLOAD_STATUSES),
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
                IMSUpload.status.in_(cls.READABLE_UPLOAD_STATUSES),
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
    def _previous_completed_for_period(cls, upload: IMSUpload) -> IMSUpload | None:
        return (
            IMSUpload.query
            .filter(
                IMSUpload.year == upload.year,
                IMSUpload.month == upload.month,
                IMSUpload.status == IMSUpload.STATUS_COMPLETED,
                IMSUpload.id != upload.id,
            )
            .order_by(IMSUpload.week_number.desc(), IMSUpload.completed_at.desc(), IMSUpload.id.desc())
            .first()
        )

    @classmethod
    def _validated_snapshot_payload(cls, upload: IMSUpload, expected_source_id: int) -> dict:
        path = cls.upload_snapshot_path(upload.id)
        if not path.is_file():
            raise RuntimeError("Önceki temiz IMS'e dönüş snapshot'ı bulunamadı.")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError("Geri dönüş snapshot'ı okunamıyor.") from exc
        if int(payload.get("version", 0)) not in cls.SUPPORTED_SNAPSHOT_VERSIONS:
            raise RuntimeError("Geri dönüş snapshot sürümü desteklenmiyor.")
        if (int(payload.get("year", 0)), int(payload.get("month", 0))) != (
            int(upload.year), int(upload.month)
        ):
            raise RuntimeError("Geri dönüş snapshot dönemi aktif IMS ile eşleşmiyor.")
        declared_source = payload.get("source_upload_id")
        if declared_source is not None and int(declared_source) != int(expected_source_id):
            raise RuntimeError("Geri dönüş snapshot kaynak IMS kimliği eşleşmiyor.")
        summaries = payload.get("summaries") or []
        summary_sources = {
            int(row["upload_id"]) for row in summaries if row.get("upload_id") is not None
        }
        if not summaries or summary_sources != {int(expected_source_id)}:
            raise RuntimeError("Geri dönüş snapshot özet kaynağı önceki IMS ile eşleşmiyor.")
        if not payload.get("targets") or not payload.get("brick_assignments"):
            raise RuntimeError("Geri dönüş snapshot'ında dönem verileri eksik.")
        if int(payload.get("version", 0)) < 3:
            raise RuntimeError("Bu IMS snapshot'ında eksiksiz master geri dönüş günlüğü yok.")
        if int(payload.get("sealed_upload_id", 0)) != int(upload.id):
            raise RuntimeError("IMS snapshot master günlüğü doğru yükleme için mühürlenmemiş.")
        if not payload.get("master_before") or not payload.get("master_after"):
            raise RuntimeError("IMS snapshot master değişiklik günlüğü eksik.")
        cls._validate_master_rollback(payload)
        return payload

    @staticmethod
    def _state_by_id(rows: list[dict]) -> dict[int, dict]:
        return {int(row["id"]): row for row in rows if row.get("id") is not None}

    @classmethod
    def _master_plan(cls, payload: dict):
        definitions = (
            ("representatives", Representative, "active"),
            ("products", Product, "is_active"),
        )
        for key, model, active_field in definitions:
            before = cls._state_by_id((payload.get("master_before") or {}).get(key) or [])
            after = cls._state_by_id((payload.get("master_after") or {}).get(key) or [])
            removed = sorted(set(before) - set(after))
            if removed:
                raise RuntimeError(f"IMS importu {key} master kaydı sildi; otomatik geri dönüş reddedildi.")
            yield key, model, active_field, before, after

    @classmethod
    def _validate_master_rollback(cls, payload: dict) -> None:
        """Refuse to overwrite a master field edited after the IMS import."""
        for key, model, _active_field, before, after in cls._master_plan(payload):
            for row_id, after_row in after.items():
                current = db.session.get(model, row_id)
                if current is None:
                    raise RuntimeError(f"IMS sonrası {key} master kaydı bulunamadı: {row_id}.")
                current_row = cls._serialize_rows([current])[0]
                before_row = before.get(row_id)
                fields = (
                    set(after_row)
                    if before_row is None
                    else {name for name in after_row if after_row.get(name) != before_row.get(name)}
                )
                conflicts = [
                    name for name in fields
                    if current_row.get(name) != after_row.get(name)
                ]
                if conflicts:
                    raise RuntimeError(
                        f"IMS sonrası {key} master kaydı ayrıca değiştirildi ({row_id}: "
                        + ", ".join(sorted(conflicts))
                        + "); güvenli geri dönüş reddedildi."
                    )

    @classmethod
    def _restore_master_state(cls, payload: dict) -> dict:
        restored = {"representatives": 0, "products": 0, "new_representatives": [], "new_products": []}
        for key, model, active_field, before, after in cls._master_plan(payload):
            new_ids = sorted(set(after) - set(before))
            restored[f"new_{key}"] = new_ids
            for row_id, before_row in before.items():
                after_row = after[row_id]
                changed = [name for name in after_row if after_row.get(name) != before_row.get(name)]
                if not changed:
                    continue
                current = db.session.get(model, row_id)
                prepared = cls._prepare_core_rows(model, [before_row])[0]
                for name in changed:
                    if name != "id" and name in prepared:
                        setattr(current, name, prepared[name])
                restored[key] += 1
            # Upload-owned facts still reference newly created masters until the
            # separate physical cleanup. Hide them atomically from all live UI.
            for row_id in new_ids:
                setattr(db.session.get(model, row_id), active_field, False)
        return restored

    @classmethod
    def _snapshot_set_for_source(cls, table, member_table, count_column, *, upload, source_id):
        from app.services.ims_rollback_guard import IMSRollbackGuard
        production_id = IMSRollbackGuard.final_applied_id(upload.year, upload.month)
        row = db.session.execute(
            sa.select(table.c.id, count_column).where(
                table.c.year == int(upload.year),
                table.c.month == int(upload.month),
                table.c.source_upload_id == int(source_id),
                table.c.production_upload_id == int(production_id),
                table.c.status.in_(("ACTIVE", "SUPERSEDED")),
            ).order_by(desc(table.c.activated_at), desc(table.c.id)).limit(1)
        ).first()
        if row is None or int(row[1] or 0) <= 0:
            raise RuntimeError("Önceki IMS için hazır ekran snapshot seti bulunamadı.")
        member_count = db.session.execute(
            sa.select(sa.func.count()).select_from(member_table).where(member_table.c.set_id == int(row[0]))
        ).scalar_one()
        if int(member_count) != int(row[1]):
            raise RuntimeError("Önceki IMS ekran snapshot seti eksik veya tutarsız.")
        return int(row[0])

    @classmethod
    def _rollback_preflight(cls, upload_id: int):
        active_job = IMSImportJob.query.filter(
            IMSImportJob.status.in_((IMSImportJob.STATUS_QUEUED, IMSImportJob.STATUS_PROCESSING))
        ).first()
        if active_job is not None:
            raise RuntimeError("Aktif IMS importu varken geri dönüş yapılamaz.")
        upload = db.session.get(IMSUpload, int(upload_id))
        if upload is None:
            raise LookupError("IMS yüklemesi bulunamadı.")
        latest = cls._latest_completed_for_period(upload)
        if upload.status != IMSUpload.STATUS_COMPLETED or latest is None or latest.id != upload.id:
            raise RuntimeError("Yalnız aktif dönemin son IMS yüklemesi geri alınabilir.")
        global_latest = IMSUpload.query.filter_by(status=IMSUpload.STATUS_COMPLETED).order_by(
            IMSUpload.year.desc(), IMSUpload.month.desc(), IMSUpload.week_number.desc(),
            IMSUpload.completed_at.desc(), IMSUpload.id.desc(),
        ).first()
        if global_latest is None or global_latest.id != upload.id:
            raise RuntimeError("Geçmiş dönem IMS'i değiştirilemez; yalnız sistemde aktif son IMS geri alınabilir.")
        from app.services.ims_rollback_guard import IMSRollbackGuard
        IMSRollbackGuard.assert_period_open(upload.year, upload.month)
        previous = cls._previous_completed_for_period(upload)
        if previous is None:
            raise RuntimeError("Aynı dönemde geri dönülebilecek önceki temiz IMS yok.")
        cls._validate_archived_source(previous.id)
        payload = cls._validated_snapshot_payload(upload, previous.id)

        from app.services.persistent_dashboard_snapshot_service import (
            PersistentDashboardSnapshotService,
        )
        _active_ims_id, production_id = PersistentDashboardSnapshotService.source_identity(
            upload.year, upload.month
        )
        captured_production_id = int(payload.get("dashboard_production_upload_id", 0))
        if production_id != captured_production_id:
            raise RuntimeError(
                "IMS yüklemesinden sonra production kaynağı değişti; eski dashboard nesliyle "
                "otomatik geri dönüş güvenli değil."
            )

        from app.services.persistent_region_snapshot_service import (
            region_snapshot_sets, region_snapshots,
        )
        from app.services.persistent_representative_snapshot_service import (
            representative_snapshot_sets, representative_snapshots,
        )
        region_set_id = cls._snapshot_set_for_source(
            region_snapshot_sets, region_snapshots, region_snapshot_sets.c.region_count,
            upload=upload, source_id=previous.id,
        )
        representative_set_id = cls._snapshot_set_for_source(
            representative_snapshot_sets, representative_snapshots,
            representative_snapshot_sets.c.representative_count,
            upload=upload, source_id=previous.id,
        )
        if not PersistentDashboardSnapshotService.generation_ready(
            upload.year, upload.month, previous.id, production_id
        ):
            raise RuntimeError("Önceki IMS için hazır dashboard snapshot nesli bulunamadı.")
        return upload, previous, payload, region_set_id, representative_set_id

    @classmethod
    def can_rollback(cls, upload: IMSUpload) -> tuple[bool, str]:
        try:
            cls._rollback_preflight(upload.id)
        except (LookupError, RuntimeError) as exc:
            db.session.rollback()
            return False, str(exc)
        return True, ""

    @classmethod
    def rollback_to_previous(cls, upload_id: int, *, actor: str | None = None) -> dict:
        upload, previous, payload, region_set_id, representative_set_id = cls._rollback_preflight(upload_id)
        from app.services.persistent_region_snapshot_service import region_snapshot_sets
        from app.services.persistent_representative_snapshot_service import representative_snapshot_sets

        year, month = int(upload.year), int(upload.month)
        try:
            cls._restore_period_snapshot(upload)
            master_result = cls._restore_master_state(payload)
            upload.status = IMSUpload.STATUS_ROLLED_BACK
            now = datetime.utcnow()
            for table, target_set_id in (
                (region_snapshot_sets, region_set_id),
                (representative_snapshot_sets, representative_set_id),
            ):
                db.session.execute(
                    table.update().where(
                        table.c.year == year,
                        table.c.month == month,
                        table.c.status == "ACTIVE",
                        table.c.id != target_set_id,
                    ).values(status="SUPERSEDED")
                )
                db.session.execute(
                    table.update().where(table.c.id == target_set_id).values(
                        status="ACTIVE", activated_at=now
                    )
                )
            db.session.add(AuditLog(
                username=(str(actor).strip() if actor else None),
                module="IMS",
                action=(
                    f"IMS_ROLLBACK from_upload={int(upload.id)} to_upload={int(previous.id)} "
                    f"period={year:04d}-{month:02d} region_set={region_set_id} "
                    f"representative_set={representative_set_id} "
                    f"master_representatives={master_result['representatives']} "
                    f"master_products={master_result['products']} "
                    f"new_representatives={len(master_result['new_representatives'])} "
                    f"new_products={len(master_result['new_products'])}"
                ),
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        cls._invalidate_runtime_caches(year, month)
        return {
            "rolled_back_upload_id": int(upload.id),
            "active_upload_id": int(previous.id),
            "year": year,
            "month": month,
            "region_snapshot_set_id": region_set_id,
            "representative_snapshot_set_id": representative_set_id,
            "master_restored": master_result,
        }

    @staticmethod
    def _invalidate_runtime_caches(year: int, month: int) -> None:
        """Best-effort invalidation after the authoritative transaction commits."""
        try:
            from app.cache.dashboard_cache import DashboardCache
            from app.cache.region_manager_snapshot_cache import RegionManagerSnapshotCache
            from app.cache.representative_analysis_cache import RepresentativeAnalysisCache
            from app.constants.dashboard_constants import DashboardConstants
            from app.services.alias_service import AliasService

            DashboardCache().invalidate_prefix(
                f"{DashboardConstants.CACHE_PREFIX}:{int(year)}:{int(month)}:"
            )
            RegionManagerSnapshotCache.clear()
            RepresentativeAnalysisCache.clear()
            AliasService.clear_cache()
        except Exception:
            current_app.logger.exception(
                "ims_rollback_cache_invalidation_failed period=%04d-%02d", year, month
            )

    @classmethod
    def can_delete(cls, upload: IMSUpload) -> tuple[bool, str]:
        if upload.status != "COMPLETED":
            return True, ""
        latest = cls._latest_completed_for_period(upload)
        if latest is None or latest.id != upload.id:
            return True, ""
        return cls.can_rollback(upload)

    @staticmethod
    def _prepare_core_rows(model, rows: list[dict]) -> list[dict]:
        columns = {column.name: column for column in model.__table__.columns}
        prepared = []
        for values in rows:
            clean = {}
            for key, value in values.items():
                column = columns.get(key)
                if column is None:
                    continue
                if value is not None and isinstance(column.type, DateTime) and isinstance(value, str):
                    value = datetime.fromisoformat(value)
                clean[key] = value
            prepared.append(clean)
        return prepared

    @classmethod
    def _restore_rows_core(cls, model, rows: list[dict]) -> None:
        prepared = cls._prepare_core_rows(model, rows)
        if prepared:
            db.session.execute(model.__table__.insert(), prepared)

    @classmethod
    def _expunge_current_state_models(cls) -> None:
        current_state_models = (Target, IMSSummary, RepresentativeBrickAssignment)
        for obj in list(db.session.identity_map.values()):
            if isinstance(obj, current_state_models):
                db.session.expunge(obj)

    @classmethod
    def _restore_period_snapshot(cls, upload: IMSUpload) -> None:
        upload_id = int(upload.id)
        year = int(upload.year)
        month = int(upload.month)
        path = cls.upload_snapshot_path(upload_id)
        if not path.exists():
            raise RuntimeError("Silme için gerekli geri dönüş snapshot'ı bulunamadı.")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("version", 0)) not in cls.SUPPORTED_SNAPSHOT_VERSIONS:
            raise RuntimeError("Geri dönüş snapshot sürümü desteklenmiyor.")
        if (int(payload.get("year", 0)), int(payload.get("month", 0))) != (year, month):
            raise RuntimeError("Geri dönüş snapshot dönemi IMS dönemiyle eşleşmiyor.")

        cls._expunge_current_state_models()

        target_table = Target.__table__
        summary_table = IMSSummary.__table__
        assignment_table = RepresentativeBrickAssignment.__table__
        db.session.execute(
            target_table.delete().where(target_table.c.year == year, target_table.c.month == month)
        )
        db.session.execute(
            summary_table.delete().where(summary_table.c.year == year, summary_table.c.month == month)
        )
        db.session.execute(
            assignment_table.delete().where(
                assignment_table.c.year == year,
                assignment_table.c.month == month,
            )
        )

        cls._restore_rows_core(Target, payload.get("targets") or [])
        cls._restore_rows_core(IMSSummary, payload.get("summaries") or [])
        cls._restore_rows_core(RepresentativeBrickAssignment, payload.get("brick_assignments") or [])

    @classmethod
    def _delete_direct_upload_children(cls, upload_id: int) -> None:
        """Delete every declared direct child of IMSUpload in dependency order.

        Runtime SQLite FK introspection can be incomplete depending on how an
        existing database was migrated. SQLAlchemy model metadata is the source
        contract used by the application itself, so use it to discover upload
        ownership. Reversing ``sorted_tables`` guarantees dependent rows such as
        IMSFact are deleted before IMSRawData.
        """
        deleted_tables = set()
        for table in reversed(db.metadata.sorted_tables):
            if table.name == IMSUpload.__tablename__:
                continue
            upload_columns = []
            for foreign_key in table.foreign_keys:
                if foreign_key.column.table.name != IMSUpload.__tablename__:
                    continue
                if foreign_key.column.name != "id":
                    continue
                upload_columns.append(foreign_key.parent)
            for column in upload_columns:
                db.session.execute(table.delete().where(column == int(upload_id)))
                deleted_tables.add(table.name)

        # Fail closed if core IMS ownership declarations unexpectedly disappear.
        required = {"ims_raw_data", "ims_facts", "ims_summary", "ims_competition_data"}
        missing = required.intersection(db.metadata.tables) - deleted_tables
        if missing:
            raise RuntimeError(
                "IMS silme sahiplik sözleşmesi eksik: " + ", ".join(sorted(missing))
            )

    @classmethod
    def _new_master_cleanup_candidates(cls, upload_id: int) -> dict:
        path = cls.upload_snapshot_path(upload_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return {"representatives": [], "products": []}
        if int(payload.get("version", 0)) < 3:
            return {"representatives": [], "products": []}
        result = {}
        for key in ("representatives", "products"):
            before = cls._state_by_id((payload.get("master_before") or {}).get(key) or [])
            after = cls._state_by_id((payload.get("master_after") or {}).get(key) or [])
            result[key] = sorted(set(after) - set(before))
        return result

    @staticmethod
    def _master_has_references(model, row_id: int) -> bool:
        for table in db.metadata.tables.values():
            if table.name == model.__tablename__:
                continue
            columns = {
                foreign_key.parent
                for foreign_key in table.foreign_keys
                if foreign_key.column.table.name == model.__tablename__
                and foreign_key.column.name == "id"
            }
            for column in columns:
                exists = db.session.execute(
                    sa.select(sa.literal(1)).select_from(table).where(column == int(row_id)).limit(1)
                ).scalar()
                if exists:
                    return True
        return False

    @classmethod
    def _delete_unreferenced_import_masters(cls, candidates: dict) -> dict:
        result = {
            "representatives_deleted": 0,
            "products_deleted": 0,
            "representatives_preserved": [],
            "products_preserved": [],
        }
        for key, model in (("representatives", Representative), ("products", Product)):
            for row_id in candidates.get(key) or []:
                row = db.session.get(model, int(row_id))
                if row is None:
                    continue
                if cls._master_has_references(model, row_id):
                    result[f"{key}_preserved"].append(int(row_id))
                    continue
                db.session.delete(row)
                result[f"{key}_deleted"] += 1
        return result

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
        latest = cls._latest_completed_for_period(upload) if upload.status == "COMPLETED" else None
        rollback_bundle = None
        if latest is not None and latest.id == int(upload.id):
            rollback_bundle = cls._rollback_preflight(upload.id)
        else:
            allowed, reason = cls.can_delete(upload)
            if not allowed:
                raise RuntimeError(reason)

        deleted_upload_id = int(upload.id)
        year, month = int(upload.year), int(upload.month)
        master_candidates = cls._new_master_cleanup_candidates(deleted_upload_id)
        hidden_key = cls.hidden_setting_key(deleted_upload_id)
        restored = rollback_bundle is not None
        master_result = None

        try:
            with db.session.no_autoflush:
                cls._delete_direct_upload_children(deleted_upload_id)
                db.session.execute(
                    Setting.__table__.delete().where(Setting.setting_key == hidden_key)
                )
                db.session.execute(
                    IMSUpload.__table__.delete().where(IMSUpload.id == deleted_upload_id)
                )
                if restored:
                    cls._restore_period_snapshot(upload)
                    _current, previous, payload, region_set_id, representative_set_id = rollback_bundle
                    master_result = cls._restore_master_state(payload)
                    from app.services.persistent_region_snapshot_service import region_snapshot_sets
                    from app.services.persistent_representative_snapshot_service import (
                        representative_snapshot_sets,
                    )

                    now = datetime.utcnow()
                    for table, target_set_id in (
                        (region_snapshot_sets, region_set_id),
                        (representative_snapshot_sets, representative_set_id),
                    ):
                        db.session.execute(
                            table.update().where(
                                table.c.year == year,
                                table.c.month == month,
                                table.c.status == "ACTIVE",
                                table.c.id != target_set_id,
                            ).values(status="SUPERSEDED")
                        )
                        db.session.execute(
                            table.update().where(table.c.id == target_set_id).values(
                                status="ACTIVE", activated_at=now
                            )
                        )
                    db.session.add(AuditLog(
                        module="IMS",
                        action=(
                            f"IMS_ROLLBACK_DELETE from_upload={deleted_upload_id} "
                            f"to_upload={int(previous.id)} period={year:04d}-{month:02d}"
                        ),
                    ))
                master_cleanup = cls._delete_unreferenced_import_masters(master_candidates)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        for suffix in (".xlsx", ".xls"):
            cls.archived_source_path(deleted_upload_id, suffix).unlink(missing_ok=True)
        cls.upload_snapshot_path(deleted_upload_id).unlink(missing_ok=True)
        if restored:
            cls._invalidate_runtime_caches(year, month)
        return {
            "deleted_upload_id": deleted_upload_id,
            "restored_previous_period_state": restored,
            "master_cleanup": master_cleanup,
            "master_restored": master_result,
        }
