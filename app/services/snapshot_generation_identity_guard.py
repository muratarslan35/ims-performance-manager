"""Prevent durable read models from accepting a reused IMS upload id.

SQLite can reuse the highest integer primary key after a physically deleted IMS
upload. Durable dashboard/region/representative snapshots are intentionally
keyed by upload id, so an old snapshot with the same numeric id must also prove
that it was created after the *current* upload completed.

This guard keeps the existing read-model architecture intact. It adds a source
freshness check and removes derived artifacts after permanent IMS deletion so a
later upload cannot collide with stale snapshot generations.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import desc

from app.extensions import db
from app.models import IMSUpload


def _source_completed_at(upload_id: int | None):
    if not upload_id:
        return None
    try:
        upload = db.session.get(IMSUpload, int(upload_id))
    except RuntimeError:
        # Some isolated filesystem tests exercise dashboard snapshot storage
        # without initializing the application's SQLAlchemy extension. In that
        # legacy-compatible mode there is no database identity to strengthen.
        return None
    if upload is None:
        return None
    return upload.completed_at or upload.uploaded_at


def _created_at(value):
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).strip().removesuffix("Z"))
    except (TypeError, ValueError):
        return None


def _fresh_for_source(*, upload_id: int, created_at) -> bool:
    """Return False only when a durable generation demonstrably predates source."""
    source_completed = _source_completed_at(upload_id)
    generation_created = _created_at(created_at)
    if source_completed is None or generation_created is None:
        # Preserve compatibility for legacy rows that predate freshness metadata.
        # New generations always carry both timestamps.
        return True
    if not isinstance(created_at, datetime):
        # Dashboard JSON stores ISO timestamps at second precision. Avoid a
        # same-second false negative against DB timestamps that retain micros.
        source_completed = source_completed.replace(microsecond=0)
    return generation_created >= source_completed


def _install_dashboard_guard():
    from app.services.persistent_dashboard_snapshot_service import (
        PersistentDashboardSnapshotService,
    )

    cls = PersistentDashboardSnapshotService
    if getattr(cls, "_source_generation_identity_guard_installed", False):
        return

    original_generation_ready = cls.generation_ready
    original_get_active = cls.get_active

    @classmethod
    def generation_ready(guarded_cls, year, month, ims_id, production_id):
        if not original_generation_ready(year, month, ims_id, production_id):
            return False
        path = guarded_cls._generation_path(year, month, ims_id, production_id)
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
            return False
        return _fresh_for_source(
            upload_id=int(ims_id),
            created_at=envelope.get("created_at"),
        )

    @classmethod
    def get_active(guarded_cls, year, month):
        """Reject stale ids without bypassing the atomic publication gate."""
        from app.services.ims_publication_service import IMSPublicationService

        # The base service owns publication visibility. Keep that decision
        # authoritative even though this compatibility guard wraps get_active.
        if IMSPublicationService.pending_job(year, month) is not None:
            return original_get_active(year, month)

        ims_id, production_id = guarded_cls.source_identity(year, month)
        generation_path = guarded_cls._generation_path(year, month, ims_id, production_id)
        stable_path = guarded_cls._path(year, month)
        for path in (generation_path, stable_path):
            try:
                envelope = json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if (
                envelope.get("version") != guarded_cls.VERSION
                or int(envelope.get("year", 0)) != int(year)
                or int(envelope.get("month", 0)) != int(month)
                or int(envelope.get("ims_upload_id", -1)) != int(ims_id)
                or int(envelope.get("production_upload_id", -1)) != int(production_id)
                or not _fresh_for_source(
                    upload_id=int(ims_id), created_at=envelope.get("created_at")
                )
            ):
                continue
            payload = envelope.get("payload")
            if not isinstance(payload, dict):
                continue
            # Preserve the legacy-pointer migration behavior of the original
            # service, but only after source freshness has been proven.
            if path != generation_path and not generation_path.exists():
                generation_path.parent.mkdir(parents=True, exist_ok=True)
                temp = generation_path.with_suffix(f".json.tmp-{os.getpid()}")
                temp.write_text(
                    json.dumps(envelope, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )
                os.replace(temp, generation_path)
            return payload

        # A new P1/P2 result does not invalidate the already-published payload
        # for the same IMS generation. Keep that stable pointer readable until
        # the exact production generation is published, while retaining the
        # reused-id freshness protection.
        try:
            envelope = json.loads(stable_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
            return None
        if (
            envelope.get("version") == guarded_cls.VERSION
            and int(envelope.get("year", 0)) == int(year)
            and int(envelope.get("month", 0)) == int(month)
            and int(envelope.get("ims_upload_id", -1)) == int(ims_id)
            and 0 <= int(envelope.get("production_upload_id", -1)) <= int(production_id)
            and _fresh_for_source(
                upload_id=int(ims_id), created_at=envelope.get("created_at")
            )
            and isinstance(envelope.get("payload"), dict)
        ):
            return envelope["payload"]
        return None

    cls.generation_ready = generation_ready
    cls.get_active = get_active
    cls._source_generation_identity_guard_installed = True


def _install_region_guard():
    from app.services.persistent_region_snapshot_service import (
        PersistentRegionSnapshotService,
        region_snapshot_sets,
        region_snapshots,
    )

    cls = PersistentRegionSnapshotService
    if getattr(cls, "_source_generation_identity_guard_installed", False):
        return

    original_build = cls.build_for_period
    original_visible_set_id = cls._visible_set_id

    def stale_current_set(year, month, ims_id, production_id):
        row = db.session.execute(
            sa.select(
                region_snapshot_sets.c.id,
                region_snapshot_sets.c.created_at,
            ).where(
                region_snapshot_sets.c.year == int(year),
                region_snapshot_sets.c.month == int(month),
                region_snapshot_sets.c.source_upload_id == int(ims_id),
                region_snapshot_sets.c.production_upload_id == int(production_id),
            ).limit(1)
        ).first()
        if row is None:
            return None
        return int(row.id) if not _fresh_for_source(
            upload_id=int(ims_id), created_at=row.created_at
        ) else None

    @classmethod
    def build_for_period(guarded_cls, year, month, **kwargs):
        year, month = int(year), int(month)
        ims_id, production_id = guarded_cls.source_identity(year, month)
        stale_set_id = stale_current_set(year, month, ims_id, production_id) if ims_id else None
        if stale_set_id is not None:
            # Keep the unique source key, but turn the collided old generation
            # back into a clean BUILDING shell for the normal builder to fill.
            db.session.execute(
                region_snapshots.delete().where(region_snapshots.c.set_id == stale_set_id)
            )
            db.session.execute(
                region_snapshot_sets.update().where(
                    region_snapshot_sets.c.id == stale_set_id
                ).values(
                    status=guarded_cls.STATUS_BUILDING,
                    region_count=0,
                    created_at=datetime.utcnow(),
                    activated_at=None,
                )
            )
            db.session.commit()
        return original_build(year, month, **kwargs)

    @classmethod
    def visible_set_id(guarded_cls, year, month):
        set_id = original_visible_set_id(year, month)
        if not set_id:
            return None
        row = db.session.execute(
            sa.select(
                region_snapshot_sets.c.source_upload_id,
                region_snapshot_sets.c.created_at,
            ).where(region_snapshot_sets.c.id == int(set_id))
        ).first()
        if row is None or _fresh_for_source(
            upload_id=int(row.source_upload_id), created_at=row.created_at
        ):
            return int(set_id) if row is not None else None

        ims_id, _production_id = guarded_cls.source_identity(year, month)
        previous = db.session.execute(
            sa.select(region_snapshot_sets.c.id).where(
                region_snapshot_sets.c.year == int(year),
                region_snapshot_sets.c.month == int(month),
                region_snapshot_sets.c.source_upload_id != int(ims_id),
                region_snapshot_sets.c.status.in_((
                    guarded_cls.STATUS_ACTIVE,
                    guarded_cls.STATUS_SUPERSEDED,
                )),
            ).order_by(
                desc(region_snapshot_sets.c.activated_at),
                desc(region_snapshot_sets.c.id),
            ).limit(1)
        ).scalar()
        return int(previous) if previous else None

    cls.build_for_period = build_for_period
    cls._visible_set_id = visible_set_id
    cls._source_generation_identity_guard_installed = True


def _install_representative_guard():
    from app.services.persistent_representative_snapshot_service import (
        PersistentRepresentativeSnapshotService,
        representative_snapshot_sets,
    )

    cls = PersistentRepresentativeSnapshotService
    if getattr(cls, "_source_generation_identity_guard_installed", False):
        return

    original_build = cls.build_for_period
    original_visible_set_id = cls._visible_set_id

    def invalidate_stale_exact(year, month, ims_id, production_id):
        rows = db.session.execute(
            sa.select(
                representative_snapshot_sets.c.id,
                representative_snapshot_sets.c.status,
                representative_snapshot_sets.c.created_at,
            ).where(
                representative_snapshot_sets.c.year == int(year),
                representative_snapshot_sets.c.month == int(month),
                representative_snapshot_sets.c.source_upload_id == int(ims_id),
                representative_snapshot_sets.c.production_upload_id == int(production_id),
                representative_snapshot_sets.c.status.in_((
                    cls.STATUS_ACTIVE,
                    cls.STATUS_BUILDING,
                )),
            )
        ).all()
        changed = False
        for row in rows:
            if _fresh_for_source(upload_id=int(ims_id), created_at=row.created_at):
                continue
            replacement = (
                cls.STATUS_SUPERSEDED
                if row.status == cls.STATUS_ACTIVE
                else cls.STATUS_FAILED
            )
            db.session.execute(
                representative_snapshot_sets.update().where(
                    representative_snapshot_sets.c.id == int(row.id)
                ).values(status=replacement)
            )
            changed = True
        if changed:
            db.session.commit()

    @classmethod
    def build_for_period(guarded_cls, year, month, **kwargs):
        year, month = int(year), int(month)
        ims_id, production_id = guarded_cls.source_identity(year, month)
        if ims_id:
            invalidate_stale_exact(year, month, ims_id, production_id)
        return original_build(year, month, **kwargs)

    @classmethod
    def visible_set_id(guarded_cls, year, month):
        set_id = original_visible_set_id(year, month)
        if not set_id:
            return None
        row = db.session.execute(
            sa.select(
                representative_snapshot_sets.c.source_upload_id,
                representative_snapshot_sets.c.created_at,
            ).where(representative_snapshot_sets.c.id == int(set_id))
        ).first()
        if row is None or _fresh_for_source(
            upload_id=int(row.source_upload_id), created_at=row.created_at
        ):
            return int(set_id) if row is not None else None

        ims_id, _production_id = guarded_cls.source_identity(year, month)
        previous = db.session.execute(
            sa.select(representative_snapshot_sets.c.id).where(
                representative_snapshot_sets.c.year == int(year),
                representative_snapshot_sets.c.month == int(month),
                representative_snapshot_sets.c.source_upload_id != int(ims_id),
                representative_snapshot_sets.c.status.in_((
                    guarded_cls.STATUS_ACTIVE,
                    guarded_cls.STATUS_SUPERSEDED,
                )),
            ).order_by(
                desc(representative_snapshot_sets.c.activated_at),
                desc(representative_snapshot_sets.c.id),
            ).limit(1)
        ).scalar()
        return int(previous) if previous else None

    cls.build_for_period = build_for_period
    cls._visible_set_id = visible_set_id
    cls._source_generation_identity_guard_installed = True


def _install_delete_cleanup():
    from app.services.ims_upload_lifecycle_service import IMSUploadLifecycleService
    from app.services.persistent_dashboard_snapshot_service import (
        PersistentDashboardSnapshotService,
    )
    from app.services.persistent_region_snapshot_service import (
        region_snapshot_sets,
        region_snapshots,
    )
    from app.services.persistent_representative_snapshot_service import (
        representative_snapshot_sets,
        representative_snapshots,
    )

    cls = IMSUploadLifecycleService
    if getattr(cls, "_snapshot_generation_cleanup_installed", False):
        return

    original_delete = cls.delete_upload

    @classmethod
    def delete_upload(guarded_cls, upload_id):
        upload = db.session.get(IMSUpload, int(upload_id))
        period = (int(upload.year), int(upload.month)) if upload is not None else None
        result = original_delete(upload_id)
        if period is None:
            return result

        year, month = period
        try:
            # These tables are derived read models and intentionally have no FK
            # to IMSUpload because rolled-back generations remain reusable.
            region_ids = db.session.execute(
                sa.select(region_snapshot_sets.c.id).where(
                    region_snapshot_sets.c.source_upload_id == int(upload_id)
                )
            ).scalars().all()
            if region_ids:
                db.session.execute(
                    region_snapshots.delete().where(region_snapshots.c.set_id.in_(region_ids))
                )
                db.session.execute(
                    region_snapshot_sets.delete().where(region_snapshot_sets.c.id.in_(region_ids))
                )

            representative_ids = db.session.execute(
                sa.select(representative_snapshot_sets.c.id).where(
                    representative_snapshot_sets.c.source_upload_id == int(upload_id)
                )
            ).scalars().all()
            if representative_ids:
                db.session.execute(
                    representative_snapshots.delete().where(
                        representative_snapshots.c.set_id.in_(representative_ids)
                    )
                )
                db.session.execute(
                    representative_snapshot_sets.delete().where(
                        representative_snapshot_sets.c.id.in_(representative_ids)
                    )
                )
            db.session.commit()
        except Exception:
            db.session.rollback()
            # Freshness checks above still make id reuse safe even if optional
            # derived-artifact cleanup fails after the business delete committed.
            from flask import current_app
            current_app.logger.exception(
                "snapshot_generation_delete_cleanup_failed upload_id=%s", upload_id
            )

        try:
            root = PersistentDashboardSnapshotService._path(year, month).parent
            for path in root.glob(
                f"dashboard-{year:04d}-{month:02d}-ims{int(upload_id)}-production*.json"
            ):
                path.unlink(missing_ok=True)
            legacy = PersistentDashboardSnapshotService._path(year, month)
            try:
                envelope = json.loads(legacy.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
                envelope = None
            if isinstance(envelope, dict) and int(envelope.get("ims_upload_id", -1)) == int(upload_id):
                legacy.unlink(missing_ok=True)
        except Exception:
            from flask import current_app
            current_app.logger.exception(
                "dashboard_generation_delete_cleanup_failed upload_id=%s", upload_id
            )
        return result

    cls.delete_upload = delete_upload
    cls._snapshot_generation_cleanup_installed = True


def install_snapshot_generation_identity_guard() -> None:
    """Install idempotent guards on all durable IMS-derived read models."""
    _install_dashboard_guard()
    _install_region_guard()
    _install_representative_guard()
    _install_delete_cleanup()
