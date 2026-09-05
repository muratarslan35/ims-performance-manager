"""Persistent, upload-versioned snapshots for the executive region cockpit.

A complete snapshot set is built sequentially after an IMS import. Readers only
see ACTIVE sets, so a partially built upload can never mix old and new regions.
If a new build fails, the previous ACTIVE set remains available.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Callable

import sqlalchemy as sa
from sqlalchemy import desc

from app.extensions import db
from app.models import IMSUpload, Representative, Target
from app.services.production_result_service import ProductionResultService
from app.services.region_market_service import RegionMarketService
from app.services.region_performance_service import RegionPerformanceService


metadata = db.metadata

region_snapshot_sets = sa.Table(
    "manager_region_snapshot_sets",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("year", sa.Integer, nullable=False),
    sa.Column("month", sa.Integer, nullable=False),
    sa.Column("source_upload_id", sa.Integer, nullable=False),
    sa.Column("production_upload_id", sa.Integer, nullable=False, server_default="0"),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("region_count", sa.Integer, nullable=False, server_default="0"),
    sa.Column("created_at", sa.DateTime, nullable=False, default=datetime.utcnow),
    sa.Column("activated_at", sa.DateTime, nullable=True),
    sa.UniqueConstraint(
        "year", "month", "source_upload_id", "production_upload_id",
        name="uq_manager_region_snapshot_set_source",
    ),
)

region_snapshots = sa.Table(
    "manager_region_snapshots",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column(
        "set_id", sa.Integer,
        sa.ForeignKey("manager_region_snapshot_sets.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("region_key", sa.String(64), nullable=False),
    sa.Column("payload_json", sa.Text, nullable=False),
    sa.Column("created_at", sa.DateTime, nullable=False, default=datetime.utcnow),
    sa.UniqueConstraint("set_id", "region_key", name="uq_manager_region_snapshot_region"),
)


class PersistentRegionSnapshotService:
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
        raise TypeError(f"Unsupported snapshot value: {type(value).__name__}")

    @classmethod
    def _json_ready(cls, value):
        """Convert nested payload keys/containers to JSON-safe equivalents.

        Region performance read models legitimately use tuple keys internally
        (for example ``source_by_month[(year, month)]``). JSON's ``default``
        hook is never called for mapping keys, so those payloads must be made
        key-safe before ``json.dumps``. This changes persistence representation
        only; live calculation services remain untouched.
        """
        if isinstance(value, dict):
            ready = {}
            for key, item in value.items():
                if isinstance(key, tuple):
                    key = "|".join(str(part) for part in key)
                elif key is not None and not isinstance(key, (str, int, float, bool)):
                    key = str(key)
                ready[key] = cls._json_ready(item)
            return ready
        if isinstance(value, (list, tuple)):
            return [cls._json_ready(item) for item in value]
        if isinstance(value, set):
            return [cls._json_ready(item) for item in sorted(value, key=str)]
        return value

    @classmethod
    def source_identity(cls, year, month):
        ims_id = db.session.query(IMSUpload.id).filter(
            IMSUpload.year == int(year),
            IMSUpload.month == int(month),
            IMSUpload.status == "COMPLETED",
        ).order_by(
            desc(IMSUpload.week_number), desc(IMSUpload.completed_at), desc(IMSUpload.id)
        ).limit(1).scalar()
        production = ProductionResultService.final_upload(int(year), int(month))
        return int(ims_id or 0), int(production.id if production is not None else 0)

    @classmethod
    def region_keys(cls, year, month):
        rows = db.session.query(Representative.region).join(
            Target, Target.representative_id == Representative.id
        ).filter(
            Target.year == int(year), Target.month == int(month),
            Representative.region.isnot(None), Representative.region != "",
        ).distinct().order_by(Representative.region.asc()).all()
        keys = [str(row[0]).strip() for row in rows if str(row[0] or "").strip()]
        if keys:
            return keys
        fallback = db.session.query(Representative.region).filter(
            Representative.region.isnot(None), Representative.region != ""
        ).distinct().order_by(Representative.region.asc()).all()
        return [str(row[0]).strip() for row in fallback if str(row[0] or "").strip()]

    @classmethod
    def _existing_set(cls, year, month, ims_id, production_id):
        return db.session.execute(
            sa.select(
                region_snapshot_sets.c.id,
                region_snapshot_sets.c.status,
                region_snapshot_sets.c.region_count,
            ).where(
                region_snapshot_sets.c.year == int(year),
                region_snapshot_sets.c.month == int(month),
                region_snapshot_sets.c.source_upload_id == int(ims_id),
                region_snapshot_sets.c.production_upload_id == int(production_id),
            )
        ).first()

    @classmethod
    def _payload_from_set(cls, set_id, region_key):
        raw = db.session.execute(
            sa.select(region_snapshots.c.payload_json).where(
                region_snapshots.c.set_id == int(set_id),
                region_snapshots.c.region_key == str(region_key).strip(),
            ).limit(1)
        ).scalar()
        return json.loads(raw) if raw else None

    @classmethod
    def _payloads_from_set(cls, set_id):
        """Read an entire published region generation in one SQL query."""
        rows = db.session.execute(
            sa.select(region_snapshots.c.region_key, region_snapshots.c.payload_json).where(
                region_snapshots.c.set_id == int(set_id)
            ).order_by(region_snapshots.c.region_key.asc())
        ).all()
        result = {}
        for region_key, raw in rows:
            try:
                result[str(region_key)] = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
        return result

    @classmethod
    def _visible_set_id(cls, year, month):
        """Resolve the one complete generation that readers may use.

        Exact current-source ACTIVE is preferred. If the current source is still
        BUILDING, the prior ACTIVE generation remains visible. FAILED/missing
        current sources return None so callers can use the compatibility path.
        """
        year, month = int(year), int(month)
        ims_id, production_id = cls.source_identity(year, month)
        if not ims_id:
            return None
        current = cls._existing_set(year, month, ims_id, production_id)
        if current and current.status == cls.STATUS_ACTIVE:
            return int(current.id)
        if not current or current.status != cls.STATUS_BUILDING:
            return None
        previous = db.session.execute(
            sa.select(region_snapshot_sets.c.id).where(
                region_snapshot_sets.c.year == year,
                region_snapshot_sets.c.month == month,
                region_snapshot_sets.c.status == cls.STATUS_ACTIVE,
                region_snapshot_sets.c.id != int(current.id),
            ).order_by(desc(region_snapshot_sets.c.activated_at), desc(region_snapshot_sets.c.id)).limit(1)
        ).scalar()
        return int(previous) if previous else None

    @classmethod
    def get_active(cls, region_key, year, month):
        set_id = cls._visible_set_id(year, month)
        return cls._payload_from_set(set_id, region_key) if set_id else None

    @classmethod
    def get_active_all(cls, year, month):
        """Return every region from the visible generation with one payload query.

        This powers the manager cockpit pack endpoint: after the page opens, all
        region HTML can be rendered from durable snapshots without any region
        performance/competition recomputation or one-request-per-region pattern.
        """
        set_id = cls._visible_set_id(year, month)
        return cls._payloads_from_set(set_id) if set_id else {}

    @classmethod
    def build_for_period(
        cls,
        year,
        month,
        *,
        progress: Callable[[int, int, str], None] | None = None,
    ):
        year, month = int(year), int(month)
        ims_id, production_id = cls.source_identity(year, month)
        if not ims_id:
            return {"status": "SKIPPED", "reason": "NO_COMPLETED_IMS", "regions": 0}

        keys = cls.region_keys(year, month)
        if not keys:
            return {"status": "SKIPPED", "reason": "NO_REGIONS", "regions": 0}

        existing = cls._existing_set(year, month, ims_id, production_id)
        if existing and existing.status == cls.STATUS_ACTIVE and int(existing.region_count or 0) == len(keys):
            return {"status": "REUSED", "set_id": int(existing.id), "regions": len(keys)}

        if existing:
            set_id = int(existing.id)
            db.session.execute(region_snapshots.delete().where(region_snapshots.c.set_id == set_id))
            db.session.execute(
                region_snapshot_sets.update().where(region_snapshot_sets.c.id == set_id).values(
                    status=cls.STATUS_BUILDING,
                    region_count=0,
                    activated_at=None,
                )
            )
        else:
            result = db.session.execute(region_snapshot_sets.insert().values(
                year=year,
                month=month,
                source_upload_id=ims_id,
                production_upload_id=production_id,
                status=cls.STATUS_BUILDING,
                region_count=0,
                created_at=datetime.utcnow(),
            ))
            set_id = int(result.inserted_primary_key[0])
        db.session.commit()

        try:
            for index, region_key in enumerate(keys, start=1):
                performance = RegionPerformanceService(region_key, year, month)
                report = performance.report()
                market = RegionMarketService(
                    report["region_key"], performance.rep_ids, year, month
                ).build()
                payload = json.dumps(
                    cls._json_ready({"report": report, "market_analysis": market}),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=cls._json_default,
                )
                db.session.execute(region_snapshots.insert().values(
                    set_id=set_id,
                    region_key=str(report["region_key"]).strip(),
                    payload_json=payload,
                    created_at=datetime.utcnow(),
                ))
                db.session.execute(
                    region_snapshot_sets.update().where(region_snapshot_sets.c.id == set_id).values(
                        region_count=index
                    )
                )
                db.session.commit()
                if progress:
                    progress(index, len(keys), str(report.get("region_name") or region_key))

            db.session.execute(
                region_snapshot_sets.update().where(
                    region_snapshot_sets.c.year == year,
                    region_snapshot_sets.c.month == month,
                    region_snapshot_sets.c.status == cls.STATUS_ACTIVE,
                    region_snapshot_sets.c.id != set_id,
                ).values(status=cls.STATUS_SUPERSEDED)
            )
            db.session.execute(
                region_snapshot_sets.update().where(region_snapshot_sets.c.id == set_id).values(
                    status=cls.STATUS_ACTIVE,
                    region_count=len(keys),
                    activated_at=datetime.utcnow(),
                )
            )
            db.session.commit()
            return {"status": "ACTIVE", "set_id": set_id, "regions": len(keys)}
        except Exception:
            db.session.rollback()
            db.session.execute(
                region_snapshot_sets.update().where(region_snapshot_sets.c.id == set_id).values(
                    status=cls.STATUS_FAILED
                )
            )
            db.session.commit()
            raise