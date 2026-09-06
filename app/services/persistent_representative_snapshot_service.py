"""Persistent upload-versioned snapshots for representative performance pages.

The calculation services remain authoritative. This module only persists their
already-built representative workspace payload so page requests do not rebuild
seven periods, market analysis and AI on every navigation.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Callable

import sqlalchemy as sa
from sqlalchemy import desc
from sqlalchemy.inspection import inspect as sa_inspect

from app.extensions import db
from app.models import IMSUpload, Representative, Target
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
    def representative_ids(cls, year, month):
        rows = db.session.query(Target.representative_id).filter(
            Target.year == int(year), Target.month == int(month)
        ).distinct().order_by(Target.representative_id.asc()).all()
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
        exact = cls._latest_exact_active(year, month, ims_id, production_id)
        if exact:
            return int(exact.id)
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

        ids = cls.representative_ids(year, month)
        if not ids:
            return {"status": "SKIPPED", "reason": "NO_REPRESENTATIVES", "representatives": 0}

        exact = cls._latest_exact_active(year, month, ims_id, production_id)
        if exact and not force and int(exact.representative_count or 0) == len(ids):
            return {"status": "REUSED", "set_id": int(exact.id), "representatives": len(ids)}

        already_building = cls._current_source_building(year, month, ims_id, production_id)
        if already_building:
            return {"status": "BUILDING", "set_id": int(already_building), "representatives": 0}

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

        try:
            total = len(ids)
            for index, representative_id in enumerate(ids, start=1):
                representative = db.session.get(Representative, representative_id)
                if representative is None:
                    continue
                workspace = build_representative_workspace_payload(representative, year, month)
                payload = json.dumps(
                    cls._json_ready(workspace),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=cls._json_default,
                )
                db.session.execute(representative_snapshots.insert().values(
                    set_id=set_id,
                    representative_id=representative_id,
                    payload_json=payload,
                    created_at=datetime.utcnow(),
                ))
                db.session.execute(
                    representative_snapshot_sets.update().where(
                        representative_snapshot_sets.c.id == set_id
                    ).values(representative_count=index)
                )
                db.session.commit()
                if progress:
                    progress(index, total, str(representative.rep_name or representative_id))

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
