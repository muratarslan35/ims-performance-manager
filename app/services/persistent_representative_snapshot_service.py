"""Persistent upload-versioned snapshots for representative performance pages.

The calculation services remain authoritative. This module only persists their
already-built representative workspace payload so page requests do not rebuild
seven periods, market analysis and AI on every navigation.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Callable

import sqlalchemy as sa
from flask import current_app
from sqlalchemy import desc
from sqlalchemy.inspection import inspect as sa_inspect

from app.extensions import db
from app.models import IMSRawData, IMSUpload, Representative
from app.services.production_result_service import ProductionResultService


metadata = db.metadata

representative_snapshot_sets = sa.Table(
    "representative_snapshot_sets",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("year", sa.Integer, nullable=False),
    sa.Column("month", sa.Integer, nullable=False),
    sa.Column("source_upload_id", sa.Integer, nullable=False),
    sa.Column("production_upload_id", sa.Integer, nullable=False, server_default="0"),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("representative_count", sa.Integer, nullable=False, server_default="0"),
    sa.Column("created_at", sa.DateTime, nullable=False, default=datetime.utcnow),
    sa.Column("activated_at", sa.DateTime, nullable=True),
)

representative_snapshots = sa.Table(
    "representative_snapshots",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column(
        "set_id",
        sa.Integer,
        sa.ForeignKey("representative_snapshot_sets.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("representative_id", sa.Integer, nullable=False),
    sa.Column("payload_json", sa.Text, nullable=False),
    sa.Column("created_at", sa.DateTime, nullable=False, default=datetime.utcnow),
    sa.UniqueConstraint(
        "set_id", "representative_id", name="uq_representative_snapshot_member"
    ),
)


class PersistentRepresentativeSnapshotService:
    STATUS_BUILDING = "BUILDING"
    STATUS_ACTIVE = "ACTIVE"
    STATUS_SUPERSEDED = "SUPERSEDED"
    STATUS_FAILED = "FAILED"
    BUILD_BATCH_SIZE = 8
    # Snapshot reads are mostly bounded SQLite I/O plus per-representative Python
    # aggregation. Three readers keep both vCPUs busy while the snapshot-local
    # read cache removes the duplicate queries that previously pushed four
    # workers into swap/I/O contention. Config can still override this value.
    BUILD_WORKERS = 3
    READ_MODEL_VERSION = 2

    @staticmethod
    def _json_default(value):
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, set):
            return sorted(value)
        if isinstance(value, SimpleNamespace):
            return vars(value)
        raise TypeError(f"Unsupported representative snapshot value: {type(value).__name__}")

    @classmethod
    def _json_ready(cls, value):
        if isinstance(value, dict):
            return {str(key): cls._json_ready(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._json_ready(item) for item in value]
        if isinstance(value, set):
            return [cls._json_ready(item) for item in sorted(value, key=str)]
        if isinstance(value, SimpleNamespace):
            return cls._json_ready(vars(value))
        try:
            inspected = sa_inspect(value)
            mapper = getattr(inspected, "mapper", None)
            if mapper is not None:
                return {
                    attr.key: cls._json_ready(getattr(value, attr.key))
                    for attr in mapper.column_attrs
                }
        except (sa.exc.NoInspectionAvailable, TypeError):
            pass
        return value

    @classmethod
    def source_identity(cls, year, month):
        ims_id = db.session.query(IMSUpload.id).filter(
            IMSUpload.year == int(year),
            IMSUpload.month == int(month),
            IMSUpload.status == "COMPLETED",
        ).order_by(
            desc(IMSUpload.week_number),
            desc(IMSUpload.completed_at),
            desc(IMSUpload.id),
        ).limit(1).scalar()
        production = ProductionResultService.final_upload(int(year), int(month))
        return int(ims_id or 0), int(production.id if production is not None else 0)

    @classmethod
    def representative_ids(cls, year, month, source_upload_id=None):
        """Return the exact roster resolved by the snapshot's IMS upload.

        Monthly targets can retain representatives from an earlier weekly roster.
        Using them here made obsolete representatives appear in new snapshots and
        needlessly rebuilt their expensive workspaces.
        """
        upload_id = int(source_upload_id or cls.source_identity(year, month)[0] or 0)
        rows = db.session.query(IMSRawData.representative_id).filter(
            IMSRawData.upload_id == upload_id,
            IMSRawData.representative_id.isnot(None),
        ).distinct().order_by(IMSRawData.representative_id.asc()).all()
        ids = [int(row[0]) for row in rows if row[0] is not None]
        if ids:
            return ids
        fallback = db.session.query(Representative.id).filter(
            Representative.active.is_(True)
        ).order_by(Representative.id.asc()).all()
        return [int(row[0]) for row in fallback]

    @classmethod
    def _current_source_building(cls, year, month, ims_id, production_id):
        return db.session.execute(
            sa.select(representative_snapshot_sets.c.id).where(
                representative_snapshot_sets.c.year == int(year),
                representative_snapshot_sets.c.month == int(month),
                representative_snapshot_sets.c.source_upload_id == int(ims_id),
                representative_snapshot_sets.c.production_upload_id == int(production_id),
                representative_snapshot_sets.c.status == cls.STATUS_BUILDING,
            ).order_by(desc(representative_snapshot_sets.c.id)).limit(1)
        ).scalar()

    @classmethod
    def _latest_exact_active(cls, year, month, ims_id, production_id):
        return db.session.execute(
            sa.select(
                representative_snapshot_sets.c.id,
                representative_snapshot_sets.c.representative_count,
            ).where(
                representative_snapshot_sets.c.year == int(year),
                representative_snapshot_sets.c.month == int(month),
                representative_snapshot_sets.c.source_upload_id == int(ims_id),
                representative_snapshot_sets.c.production_upload_id == int(production_id),
                representative_snapshot_sets.c.status == cls.STATUS_ACTIVE,
            ).order_by(
                desc(representative_snapshot_sets.c.activated_at),
                desc(representative_snapshot_sets.c.id),
            ).limit(1)
        ).first()

    @classmethod
    def _visible_set_id(cls, year, month):
        year, month = int(year), int(month)
        ims_id, production_id = cls.source_identity(year, month)
        if not ims_id:
            return None
        from app.services.ims_publication_service import IMSPublicationService
        if IMSPublicationService.pending_job(year, month) is not None:
            previous = db.session.execute(
                sa.select(representative_snapshot_sets.c.id).where(
                    representative_snapshot_sets.c.year == year,
                    representative_snapshot_sets.c.month == month,
                    representative_snapshot_sets.c.status == cls.STATUS_ACTIVE,
                    representative_snapshot_sets.c.source_upload_id != int(ims_id),
                ).order_by(desc(representative_snapshot_sets.c.activated_at), desc(representative_snapshot_sets.c.id)).limit(1)
            ).scalar()
            # Publication is all-or-nothing across dashboard, region and
            # representative read models. Never fall through to the current
            # generation while the IMS job is still pending publication.
            return int(previous) if previous else None
        exact = cls._latest_exact_active(year, month, ims_id, production_id)
        if exact:
            return int(exact.id)

        # A finalized production upload may arrive weeks later than the IMS.
        # Keep the last ACTIVE representative generation for the same IMS
        # visible until the newer production generation is fully published.
        same_ims_previous = db.session.execute(
            sa.select(representative_snapshot_sets.c.id).where(
                representative_snapshot_sets.c.year == year,
                representative_snapshot_sets.c.month == month,
                representative_snapshot_sets.c.source_upload_id == int(ims_id),
                representative_snapshot_sets.c.production_upload_id <= int(production_id),
                representative_snapshot_sets.c.status == cls.STATUS_ACTIVE,
            ).order_by(
                desc(representative_snapshot_sets.c.production_upload_id),
                desc(representative_snapshot_sets.c.activated_at),
                desc(representative_snapshot_sets.c.id),
            ).limit(1)
        ).scalar()
        if same_ims_previous:
            return int(same_ims_previous)

        building = cls._current_source_building(year, month, ims_id, production_id)
        if not building:
            return None
        previous = db.session.execute(
            sa.select(representative_snapshot_sets.c.id).where(
                representative_snapshot_sets.c.year == year,
                representative_snapshot_sets.c.month == month,
                representative_snapshot_sets.c.status == cls.STATUS_ACTIVE,
            ).order_by(
                desc(representative_snapshot_sets.c.activated_at),
                desc(representative_snapshot_sets.c.id),
            ).limit(1)
        ).scalar()
        return int(previous) if previous else None

    @classmethod
    def get_active(cls, representative_id, year, month):
        set_id = cls._visible_set_id(year, month)
        if not set_id:
            return None
        raw = db.session.execute(
            sa.select(representative_snapshots.c.payload_json).where(
                representative_snapshots.c.set_id == int(set_id),
                representative_snapshots.c.representative_id == int(representative_id),
            ).limit(1)
        ).scalar()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return None

    @classmethod
    def _payloads_from_set(cls, set_id, representative_ids):
        ids = sorted({int(item) for item in representative_ids if item is not None})
        if not ids or not set_id:
            return {}
        rows = db.session.execute(
            sa.select(
                representative_snapshots.c.representative_id,
                representative_snapshots.c.payload_json,
            ).where(
                representative_snapshots.c.set_id == int(set_id),
                representative_snapshots.c.representative_id.in_(ids),
            )
        ).all()
        result = {}
        for representative_id, raw in rows:
            try:
                result[int(representative_id)] = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
        return result

    @classmethod
    def get_active_many(cls, representative_ids, year, month):
        """Read the currently visible representative generation in one query."""
        set_id = cls._visible_set_id(year, month)
        return cls._payloads_from_set(set_id, representative_ids)

    @classmethod
    def get_exact_active_many(cls, representative_ids, year, month):
        """Read the exact current-source ACTIVE generation behind publication gate."""
        year, month = int(year), int(month)
        ims_id, production_id = cls.source_identity(year, month)
        exact = cls._latest_exact_active(year, month, ims_id, production_id)
        set_id = int(exact.id) if exact else None
        return cls._payloads_from_set(set_id, representative_ids)

    @classmethod
    def _set_read_model_version(cls, set_id):
        raw = db.session.execute(
            sa.select(representative_snapshots.c.payload_json).where(
                representative_snapshots.c.set_id == int(set_id)
            ).order_by(representative_snapshots.c.representative_id.asc()).limit(1)
        ).scalar()
        if not raw:
            return 0
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return 0
        return int(payload.get("read_model_version") or 0)

    @classmethod
    def rebuild_exact_members(cls, year, month, representative_ids):
        """Rebuild only selected members of the exact current-source generation.

        This is intended for maintenance of a hidden/current generation after a
        semantic rule change. The selected members are removed, the same set is
        returned to BUILDING, and the normal resumable batch builder calculates
        only those missing representatives.
        """
        year, month = int(year), int(month)
        ims_id, production_id = cls.source_identity(year, month)
        exact = cls._latest_exact_active(year, month, ims_id, production_id)
        if exact is None:
            return {"status": "SKIPPED", "reason": "NO_EXACT_ACTIVE", "representatives": 0}

        roster = set(cls.representative_ids(year, month, ims_id))
        selected = sorted({
            int(item) for item in representative_ids
            if item is not None and int(item) in roster
        })
        if not selected:
            return {"status": "REUSED", "set_id": int(exact.id), "representatives": len(roster), "rebuilt": 0}

        set_id = int(exact.id)
        db.session.execute(
            representative_snapshots.delete().where(
                representative_snapshots.c.set_id == set_id,
                representative_snapshots.c.representative_id.in_(selected),
            )
        )
        remaining = int(db.session.execute(
            sa.select(sa.func.count()).select_from(representative_snapshots).where(
                representative_snapshots.c.set_id == set_id
            )
        ).scalar() or 0)
        db.session.execute(
            representative_snapshot_sets.update().where(
                representative_snapshot_sets.c.id == set_id
            ).values(
                status=cls.STATUS_BUILDING,
                representative_count=remaining,
                activated_at=None,
            )
        )
        db.session.commit()
        current_app.logger.warning(
            "representative_snapshot_members_invalidated "
            "year=%s month=%s set_id=%s ims_upload_id=%s production_upload_id=%s "
            "members=%s remaining=%s",
            year, month, set_id, int(ims_id), int(production_id), selected, remaining,
        )
        result = cls.build_for_period(year, month, force=False)
        result["rebuilt"] = len(selected)
        result["rebuilt_representative_ids"] = selected
        return result

    @classmethod
    def build_for_period(
        cls,
        year,
        month,
        *,
        force: bool = False,
        progress: Callable[[int, int, str], None] | None = None,
    ):
        year, month = int(year), int(month)
        ims_id, production_id = cls.source_identity(year, month)
        if not ims_id:
            return {"status": "SKIPPED", "reason": "NO_COMPLETED_IMS", "representatives": 0}

        ids = cls.representative_ids(year, month, ims_id)
        if not ids:
            return {"status": "SKIPPED", "reason": "NO_REPRESENTATIVES", "representatives": 0}

        exact = cls._latest_exact_active(year, month, ims_id, production_id)
        if (
            exact
            and not force
            and int(exact.representative_count or 0) == len(ids)
            and cls._set_read_model_version(exact.id) >= cls.READ_MODEL_VERSION
        ):
            return {"status": "REUSED", "set_id": int(exact.id), "representatives": len(ids)}

        already_building = cls._current_source_building(year, month, ims_id, production_id)
        set_id = None
        completed = 0
        build_ids = list(ids)
        if already_building:
            # Any exact-source BUILDING generation is durable resumable work.
            # IMS publication retries use force=False, while production refreshes
            # may use force=True; both must resume instead of returning BUILDING
            # forever after a worker restart or interrupted final activation.
            # Compatible rows are derived cache for the same IMS/production
            # identity, so reuse them and calculate only the missing roster.
            existing_rows = db.session.execute(
                sa.select(representative_snapshots.c.representative_id).where(
                    representative_snapshots.c.set_id == int(already_building)
                )
            ).all()
            existing_ids = {
                int(row[0]) for row in existing_rows if row[0] is not None
            }
            expected_ids = set(ids)
            existing_version = (
                cls._set_read_model_version(already_building)
                if existing_ids
                else cls.READ_MODEL_VERSION
            )
            can_resume = (
                existing_ids.issubset(expected_ids)
                and int(existing_version or 0) >= cls.READ_MODEL_VERSION
            )
            if can_resume:
                set_id = int(already_building)
                completed = len(existing_ids)
                build_ids = [
                    representative_id
                    for representative_id in ids
                    if representative_id not in existing_ids
                ]
                db.session.execute(
                    representative_snapshot_sets.update().where(
                        representative_snapshot_sets.c.id == set_id
                    ).values(representative_count=completed)
                )
                db.session.commit()
                current_app.logger.warning(
                    "representative_snapshot_partial_build_resumed "
                    "year=%s month=%s set_id=%s ims_upload_id=%s "
                    "production_upload_id=%s completed=%s remaining=%s",
                    year, month, set_id, int(ims_id), int(production_id),
                    completed, len(build_ids),
                )
            else:
                db.session.execute(
                    representative_snapshot_sets.update().where(
                        representative_snapshot_sets.c.id == int(already_building)
                    ).values(status=cls.STATUS_FAILED)
                )
                db.session.commit()
                current_app.logger.warning(
                    "representative_snapshot_stale_building_retired "
                    "year=%s month=%s set_id=%s ims_upload_id=%s "
                    "production_upload_id=%s existing=%s version=%s",
                    year, month, int(already_building), int(ims_id),
                    int(production_id), len(existing_ids), existing_version,
                )

        if set_id is None:
            result = db.session.execute(representative_snapshot_sets.insert().values(
                year=year,
                month=month,
                source_upload_id=ims_id,
                production_upload_id=production_id,
                status=cls.STATUS_BUILDING,
                representative_count=0,
                created_at=datetime.utcnow(),
            ))
            set_id = int(result.inserted_primary_key[0])
            db.session.commit()

        # Import lazily to avoid changing the existing calculator installation order.
        from app.services.representative_period_workspace import build_representative_workspace_payload
        from app.services.representative_query_optimizer import use_snapshot_upload_ids

        try:
            total = len(ids)
            app = current_app._get_current_object()
            batch_size = max(1, int(app.config.get("REPRESENTATIVE_SNAPSHOT_BATCH_SIZE", cls.BUILD_BATCH_SIZE)))
            workers = max(1, int(app.config.get("REPRESENTATIVE_SNAPSHOT_WORKERS", cls.BUILD_WORKERS)))
            if app.testing:
                workers = 1

            # Resolve every period source once for the whole representative
            # generation. The workspace may open current and previous market
            # months for seven UI periods; without this pin each representative
            # repeated identical "latest completed upload" queries.
            period_start = (year - 1, 12)
            period_keys = [period_start] + [(year, value) for value in range(1, month + 1)]
            source_rows = IMSUpload.query.filter(
                IMSUpload.status == IMSUpload.STATUS_COMPLETED,
                sa.tuple_(IMSUpload.year, IMSUpload.month).in_(period_keys),
            ).order_by(
                IMSUpload.year.asc(), IMSUpload.month.asc(),
                IMSUpload.week_number.desc(), IMSUpload.completed_at.desc(), IMSUpload.id.desc(),
            ).all()
            snapshot_upload_ids = {}
            for source in source_rows:
                snapshot_upload_ids.setdefault((int(source.year), int(source.month)), int(source.id))
            for period_key in period_keys:
                snapshot_upload_ids.setdefault(period_key, None)

            def calculate(representative_id):
                # Every worker owns an application context and therefore its own
                # scoped SQLAlchemy session. Workers only read; SQLite writes stay
                # serialized in the parent after the complete batch is ready.
                with app.app_context(), use_snapshot_upload_ids(snapshot_upload_ids):
                    representative = db.session.get(Representative, representative_id)
                    if representative is None:
                        return None
                    name = str(representative.rep_name or representative_id)
                    workspace = build_representative_workspace_payload(representative, year, month)
                    payload = json.dumps(
                        cls._json_ready(workspace),
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=cls._json_default,
                    )
                    db.session.rollback()
                    return representative_id, name, payload

            # completed may already include persisted representatives
            # when a worker restart resumes the same BUILDING generation.
            # Keep one executor for the whole generation. Recreating DB reader
            # threads for every eight representatives discards warm connections
            # and caches, and creates avoidable allocator pressure.
            pool = ThreadPoolExecutor(max_workers=workers) if workers > 1 else None
            try:
                for offset in range(0, len(build_ids), batch_size):
                    batch_ids = build_ids[offset:offset + batch_size]
                    calculated = (
                        list(pool.map(calculate, batch_ids))
                        if pool is not None
                        else [calculate(representative_id) for representative_id in batch_ids]
                    )
                    rows = [item for item in calculated if item is not None]
                    if rows:
                        db.session.execute(representative_snapshots.insert(), [
                            {
                                "set_id": set_id,
                                "representative_id": representative_id,
                                "payload_json": payload,
                                "created_at": datetime.utcnow(),
                            }
                            for representative_id, _name, payload in rows
                        ])
                    completed += len(rows)
                    db.session.execute(
                        representative_snapshot_sets.update().where(
                            representative_snapshot_sets.c.id == set_id
                        ).values(representative_count=completed)
                    )
                    db.session.commit()
                    if progress:
                        first_name = rows[0][1] if rows else str(batch_ids[0])
                        last_name = rows[-1][1] if rows else str(batch_ids[-1])
                        progress(completed, total, f"{first_name} – {last_name}")
            finally:
                if pool is not None:
                    pool.shutdown(wait=True)

            db.session.execute(
                representative_snapshot_sets.update().where(
                    representative_snapshot_sets.c.year == year,
                    representative_snapshot_sets.c.month == month,
                    representative_snapshot_sets.c.status == cls.STATUS_ACTIVE,
                    representative_snapshot_sets.c.id != set_id,
                ).values(status=cls.STATUS_SUPERSEDED)
            )
            db.session.execute(
                representative_snapshot_sets.update().where(
                    representative_snapshot_sets.c.id == set_id
                ).values(
                    status=cls.STATUS_ACTIVE,
                    representative_count=len(ids),
                    activated_at=datetime.utcnow(),
                )
            )
            db.session.commit()
            return {"status": "ACTIVE", "set_id": set_id, "representatives": len(ids)}
        except Exception:
            db.session.rollback()
            db.session.execute(
                representative_snapshot_sets.update().where(
                    representative_snapshot_sets.c.id == set_id
                ).values(status=cls.STATUS_FAILED)
            )
            db.session.commit()
            raise
