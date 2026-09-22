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
from app.models import IMSUpload, ProductionResultUpload, Representative, Target
from app.services.production_result_service import ProductionResultService
from app.services.region_market_service import RegionMarketService, repair_duplicated_rival_totals
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
    READ_MODEL_VERSION = 4
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
        payload = json.loads(raw) if raw else None
        return repair_duplicated_rival_totals(payload)

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
                result[str(region_key)] = repair_duplicated_rival_totals(
                    json.loads(raw)
                )
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
        from app.services.ims_publication_service import IMSPublicationService
        if IMSPublicationService.pending_job(year, month) is not None:
            previous = db.session.execute(
                sa.select(region_snapshot_sets.c.id).where(
                    region_snapshot_sets.c.year == year,
                    region_snapshot_sets.c.month == month,
                    region_snapshot_sets.c.status == cls.STATUS_ACTIVE,
                    region_snapshot_sets.c.source_upload_id != int(ims_id),
                ).order_by(desc(region_snapshot_sets.c.activated_at), desc(region_snapshot_sets.c.id)).limit(1)
            ).scalar()
            # Do not fall through to the current IMS while publication
            # is pending. If this is the first IMS for the month there may be no
            # previous same-period generation, in which case readers must wait
            # rather than expose a partial new generation.
            return int(previous) if previous else None
        current = cls._existing_set(year, month, ims_id, production_id)
        if current and current.status == cls.STATUS_ACTIVE:
            return int(current.id)

        # Late production must replace the read model atomically. Until the
        # current P1/P2 generation is ACTIVE, keep the latest ACTIVE generation
        # belonging to the same IMS upload visible. This preserves historical
        # navigation without ever crossing an IMS publication boundary.
        same_ims_previous = db.session.execute(
            sa.select(region_snapshot_sets.c.id).where(
                region_snapshot_sets.c.year == year,
                region_snapshot_sets.c.month == month,
                region_snapshot_sets.c.source_upload_id == int(ims_id),
                region_snapshot_sets.c.production_upload_id <= int(production_id),
                region_snapshot_sets.c.status == cls.STATUS_ACTIVE,
                *(
                    [region_snapshot_sets.c.id != int(current.id)]
                    if current else []
                ),
            ).order_by(
                desc(region_snapshot_sets.c.production_upload_id),
                desc(region_snapshot_sets.c.activated_at),
                desc(region_snapshot_sets.c.id),
            ).limit(1)
        ).scalar()
        if same_ims_previous:
            return int(same_ims_previous)

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
    def get_active_for_visible_upload(cls, region_key, year, month, source_upload_id):
        """Read the published region payload for an already-resolved visible IMS.

        PeriodService has already applied the IMS publication gate before the
        region route calls this method. Reusing that source id avoids repeating
        pending-job/progress-file checks on every map click. The current
        production-result identity is resolved inside the same SQL statement so
        a newly applied P1/P2 result cannot serve an older ACTIVE payload.
        """
        if not source_upload_id:
            return None

        year, month = int(year), int(month)
        production_id = (
            sa.select(ProductionResultUpload.id)
            .where(
                ProductionResultUpload.year == year,
                ProductionResultUpload.month == month,
                ProductionResultUpload.status == ProductionResultUpload.STATUS_APPLIED,
            )
            .order_by(
                ProductionResultUpload.production_stage.desc(),
                ProductionResultUpload.applied_at.desc(),
                ProductionResultUpload.id.desc(),
            )
            .limit(1)
            .scalar_subquery()
        )
        raw = db.session.execute(
            sa.select(region_snapshots.c.payload_json)
            .select_from(
                region_snapshots.join(
                    region_snapshot_sets,
                    region_snapshot_sets.c.id == region_snapshots.c.set_id,
                )
            )
            .where(
                region_snapshot_sets.c.year == year,
                region_snapshot_sets.c.month == month,
                region_snapshot_sets.c.source_upload_id == int(source_upload_id),
                region_snapshot_sets.c.production_upload_id == sa.func.coalesce(production_id, 0),
                region_snapshot_sets.c.status == cls.STATUS_ACTIVE,
                region_snapshots.c.region_key == str(region_key).strip(),
            )
            .order_by(
                desc(region_snapshot_sets.c.activated_at),
                desc(region_snapshot_sets.c.id),
            )
            .limit(1)
        ).scalar()
        payload = json.loads(raw) if raw else None
        return repair_duplicated_rival_totals(payload)

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

    @staticmethod
    def _representative_ids(report):
        monthly = (((report or {}).get("periods") or {}).get("monthly") or {})
        return sorted({
            int(item["representative_id"])
            for item in monthly.get("representatives") or []
            if item.get("representative_id") is not None
            and item.get("active") is not False
        })

    @classmethod
    def _embed_representative_products(cls, report, year, month, workspaces):
        """Embed box-target rows from already-built representative read models."""
        periods = (report or {}).get("periods") or {}
        quarter_key = f"q{((int(month) - 1) // 3) + 1}"
        wanted = ("monthly", quarter_key)
        if all((periods.get(key) or {}).get("representative_products") for key in wanted):
            return report

        rep_meta = {}
        for key in wanted:
            for item in (periods.get(key) or {}).get("representatives") or []:
                representative_id = item.get("representative_id")
                if representative_id is None:
                    continue
                rep_meta[int(representative_id)] = {
                    "representative_name": item.get("representative_name"),
                    "city": item.get("city") or "-",
                    "active": bool(item.get("active")),
                    "is_vacant": bool(item.get("is_vacant")),
                }

        for key in wanted:
            period = periods.get(key) or {}
            if period.get("representative_products"):
                continue
            rows = []
            for representative_id, meta in rep_meta.items():
                workspace = (workspaces or {}).get(representative_id) or {}
                snapshot = ((workspace.get("snapshots") or {}).get(key) or {})
                for item in snapshot.get("products") or []:
                    product = item.get("product") or {}
                    if isinstance(product, dict):
                        product_id = product.get("id")
                        product_name = product.get("product_name")
                        display_order = product.get("display_order")
                    else:
                        product_id = getattr(product, "id", None)
                        product_name = getattr(product, "product_name", None)
                        display_order = getattr(product, "display_order", None)
                    if product_id is None:
                        product_id = item.get("product_id")
                    if product_id is None:
                        continue
                    actual_unit = item.get("actual_unit")
                    rows.append({
                        "representative_id": representative_id,
                        **meta,
                        "product_id": int(product_id),
                        "product_name": product_name or item.get("product_name") or f"Ürün {product_id}",
                        "product_display_order": int(display_order or 999),
                        "target_unit": item.get("target_unit") or 0,
                        "actual_unit": actual_unit,
                        "unit_complete": actual_unit is not None,
                    })
            rows.sort(key=lambda item: (
                str(item.get("representative_name") or "").casefold(),
                int(item.get("product_display_order") or 999),
                str(item.get("product_name") or "").casefold(),
            ))
            period["representative_products"] = rows
            periods[key] = period
        report["periods"] = periods
        return report

    @classmethod
    def _embed_national_product_realizations(cls, report, dashboard_payload):
        """Attach NATIONAL percentages from the already-published dashboard snapshot."""
        national = (dashboard_payload or {}).get("executive_metrics") or {}
        by_id = {
            int(item["product_id"]): item.get("realization_percent")
            for item in national.get("products") or []
            if item.get("product_id") is not None
        }
        by_name = {
            str(item.get("product_name") or "").strip().casefold(): item.get("realization_percent")
            for item in national.get("products") or []
            if str(item.get("product_name") or "").strip()
        }
        monthly = (((report or {}).get("periods") or {}).get("monthly") or {})
        for item in monthly.get("products") or []:
            product_id = item.get("product_id")
            value = by_id.get(int(product_id)) if product_id is not None else None
            if value is None:
                value = by_name.get(str(item.get("product_name") or "").strip().casefold())
            item["national_realization_percent"] = value
        return report

    @classmethod
    def upgrade_national_realizations_for_period(cls, year, month):
        """Upgrade existing region snapshots without re-running report calculations."""
        from app.services.persistent_dashboard_snapshot_service import (
            PersistentDashboardSnapshotService,
        )

        set_id = cls._visible_set_id(year, month)
        if not set_id:
            return {"status": "WAITING_REGION", "regions": 0}
        payloads = cls._payloads_from_set(set_id)
        dashboard_payload = PersistentDashboardSnapshotService.get_stable(year, month) or {}
        now = datetime.utcnow()
        for region_key, payload in payloads.items():
            enriched = dict(payload or {})
            enriched["report"] = cls._embed_national_product_realizations(
                enriched.get("report") or {}, dashboard_payload
            )
            enriched["read_model_version"] = cls.READ_MODEL_VERSION
            enriched["read_model_ready_at"] = now.isoformat(timespec="seconds") + "Z"
            db.session.execute(
                region_snapshots.update().where(
                    region_snapshots.c.set_id == int(set_id),
                    region_snapshots.c.region_key == str(region_key),
                ).values(payload_json=json.dumps(
                    cls._json_ready(enriched), ensure_ascii=False,
                    separators=(",", ":"), default=cls._json_default,
                ))
            )
        db.session.commit()
        return {"status": "ENRICHED", "set_id": int(set_id), "regions": len(payloads)}

    @classmethod
    def enrich_for_period(cls, year, month):
        """Finalize region payloads once from already-published read models.

        The steady-state region request must never re-run representative, market
        or AI calculations. This method is called after representative read
        models are ready (and can also safely backfill an older active set once).
        """
        year, month = int(year), int(month)
        set_id = cls._visible_set_id(year, month)
        if not set_id:
            return {"status": "WAITING_REGION", "regions": 0}

        payloads = cls._payloads_from_set(set_id)
        if not payloads:
            return {"status": "WAITING_REGION", "regions": 0}
        if all(int((payload or {}).get("read_model_version") or 0) >= cls.READ_MODEL_VERSION for payload in payloads.values()):
            return {"status": "REUSED", "set_id": int(set_id), "regions": len(payloads)}

        from app.services.persistent_dashboard_snapshot_service import (
            PersistentDashboardSnapshotService,
        )
        from app.services.persistent_representative_snapshot_service import (
            PersistentRepresentativeSnapshotService,
        )
        from app.services.region_ai_snapshot_service import RegionAISnapshotService
        from app.services.scoped_ai_insight_service import ScopedAIInsightService

        current_rep_ids = sorted({
            representative_id
            for payload in payloads.values()
            for representative_id in cls._representative_ids((payload or {}).get("report") or {})
        })
        current_workspaces = PersistentRepresentativeSnapshotService.get_active_many(
            current_rep_ids, year, month
        ) if current_rep_ids else {}
        if current_rep_ids and len(current_workspaces) < len(current_rep_ids):
            return {
                "status": "WAITING_REPRESENTATIVES",
                "set_id": int(set_id),
                "regions": len(payloads),
                "representatives": len(current_workspaces),
                "expected_representatives": len(current_rep_ids),
            }

        previous_year, previous_month = RegionAISnapshotService.previous_period(year, month)
        previous_payloads = cls.get_active_all(previous_year, previous_month)
        previous_rep_ids = sorted({
            representative_id
            for payload in previous_payloads.values()
            for representative_id in cls._representative_ids((payload or {}).get("report") or {})
        })
        previous_workspaces = PersistentRepresentativeSnapshotService.get_active_many(
            previous_rep_ids, previous_year, previous_month
        ) if previous_rep_ids else {}
        dashboard_payload = PersistentDashboardSnapshotService.get_stable(year, month) or {}

        updates = []
        now = datetime.utcnow()
        for region_key, payload in payloads.items():
            report = (payload or {}).get("report") or {}
            market_analysis = (payload or {}).get("market_analysis") or {}

            # Region AI must never see the all-Türkiye representative workspace
            # bundle. Select only representatives belonging to this region before
            # any brick-level zero-exit/loss analysis is built.
            current_region_rep_ids = cls._representative_ids(report)
            current_region_workspaces = {
                representative_id: current_workspaces[representative_id]
                for representative_id in current_region_rep_ids
                if representative_id in current_workspaces
            }
            report = cls._embed_representative_products(
                report, year, month, current_region_workspaces
            )
            report = cls._embed_national_product_realizations(report, dashboard_payload)

            previous_payload = previous_payloads.get(str(region_key)) or {}
            previous_market_analysis = previous_payload.get("market_analysis") or {}
            previous_report = previous_payload.get("report") or {}
            previous_region_rep_ids = cls._representative_ids(previous_report)
            previous_region_workspaces = {
                representative_id: previous_workspaces[representative_id]
                for representative_id in previous_region_rep_ids
                if representative_id in previous_workspaces
            }

            ai_report = ScopedAIInsightService.build(
                scope_type="region",
                scope_name=report.get("region_name") or str(region_key),
                periods=report.get("periods") or {},
                market_analysis=market_analysis,
            )
            ai_report["region_snapshot_intelligence"] = RegionAISnapshotService.build(
                report=report,
                market_analysis=market_analysis,
                dashboard_payload=dashboard_payload,
                previous_market_analysis=previous_market_analysis,
                current_workspaces=current_region_workspaces,
                previous_workspaces=previous_region_workspaces,
                year=year,
                month=month,
            )

            enriched = dict(payload or {})
            enriched["report"] = report
            enriched["ai_report"] = ai_report
            enriched["read_model_version"] = cls.READ_MODEL_VERSION
            enriched["read_model_ready_at"] = now.isoformat(timespec="seconds") + "Z"
            updates.append({
                "region_key": str(region_key),
                "payload_json": json.dumps(
                    cls._json_ready(enriched),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=cls._json_default,
                ),
            })

        try:
            for item in updates:
                db.session.execute(
                    region_snapshots.update().where(
                        region_snapshots.c.set_id == int(set_id),
                        region_snapshots.c.region_key == item["region_key"],
                    ).values(payload_json=item["payload_json"])
                )
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        return {"status": "ENRICHED", "set_id": int(set_id), "regions": len(updates)}

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
            return {"status": "SKIPPED", "reason": "NO_COMPLETED_IMS", "regions": 0}

        keys = cls.region_keys(year, month)
        if not keys:
            return {"status": "SKIPPED", "reason": "NO_REGIONS", "regions": 0}

        existing = cls._existing_set(year, month, ims_id, production_id)
        existing_complete = bool(
            existing
            and existing.status == cls.STATUS_ACTIVE
            and int(existing.region_count or 0) == len(keys)
        )
        if existing_complete and not force:
            return {"status": "REUSED", "set_id": int(existing.id), "regions": len(keys)}

        # A late production file changes Q/YTD/previous-period values of later
        # months without changing those later months' own IMS/production ids.
        # For those dependency refreshes, calculate every region first and swap
        # the complete ACTIVE generation in one transaction. Readers keep seeing
        # the previous ACTIVE payload until the replacement commits.
        if existing_complete and force:
            set_id = int(existing.id)
            replacement_rows = []
            for index, region_key in enumerate(keys, start=1):
                performance = RegionPerformanceService(region_key, year, month)
                report = performance.report()
                market = RegionMarketService(
                    report["region_key"], performance.rep_ids, year, month
                ).build()
                replacement_rows.append({
                    "set_id": set_id,
                    "region_key": str(report["region_key"]).strip(),
                    "payload_json": json.dumps(
                        cls._json_ready({
                            "report": report,
                            "market_analysis": market,
                        }),
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=cls._json_default,
                    ),
                    "created_at": datetime.utcnow(),
                })
                if progress:
                    progress(
                        index,
                        len(keys),
                        str(report.get("region_name") or region_key),
                    )

            now = datetime.utcnow()
            try:
                db.session.execute(
                    region_snapshots.delete().where(
                        region_snapshots.c.set_id == set_id
                    )
                )
                if replacement_rows:
                    db.session.execute(region_snapshots.insert(), replacement_rows)
                db.session.execute(
                    region_snapshot_sets.update().where(
                        region_snapshot_sets.c.id == set_id
                    ).values(
                        status=cls.STATUS_ACTIVE,
                        region_count=len(keys),
                        created_at=now,
                        activated_at=now,
                    )
                )
                db.session.commit()
            except Exception:
                db.session.rollback()
                raise
            return {
                "status": "ACTIVE",
                "set_id": set_id,
                "regions": len(keys),
                "forced": True,
            }

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
