"""Persistent queue for read-model refreshes after production results.

Production uploads are accepted by the web process, while dashboard, region,
and representative snapshot generation belongs to the existing single IMS
worker. A tiny filesystem queue keeps that work durable, serial, and behind any
IMS job already in progress.

A production result is authoritative for its own month and for every later
snapshot in the same calendar year that contains Q/YTD/previous-period values.
December also affects the following January comparison. Those dependent periods
are therefore refreshed as one production-finalization cascade.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from flask import current_app

from app.extensions import db
from app.models import IMSUpload, ProductionResultUpload, Target


class RepresentativeSnapshotRefreshQueue:
    @staticmethod
    def _root() -> Path:
        root = Path(current_app.instance_path) / "representative_refresh_queue"
        root.mkdir(parents=True, exist_ok=True)
        return root

    @classmethod
    def _path(cls, year: int, month: int) -> Path:
        return cls._root() / f"{int(year):04d}-{int(month):02d}.json"

    @staticmethod
    def _shift_month(year: int, month: int, delta: int = 1) -> tuple[int, int]:
        ordinal = int(year) * 12 + int(month) - 1 + int(delta)
        return ordinal // 12, ordinal % 12 + 1

    @staticmethod
    def _naive_utc(value):
        if value is None:
            return None
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.strip().removesuffix("Z"))
            except (TypeError, ValueError):
                return None
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    @staticmethod
    def _dependency_cutoff(
        source_year: int,
        source_month: int,
        target_year: int,
        target_month: int,
        cutoff,
    ):
        """Require recency only for downstream periods.

        The production month itself already carries the finalized production
        upload in its snapshot source identity. Once all exact-source dashboard,
        region and representative read models are complete, comparing their
        timestamps to applied_at adds no safety and can requeue an already
        accepted month after a targeted repair. Later Q/YTD-dependent periods do
        not carry that source upload in their own identity, so they must remain
        newer than the production cutoff.
        """
        if (
            int(source_year) == int(target_year)
            and int(source_month) == int(target_month)
        ):
            return None
        return cutoff

    @classmethod
    def enqueue(cls, year: int, month: int, *, reason: str) -> dict:
        """Atomically keep one newest refresh request per target period.

        Reconciliation runs repeatedly while the worker is idle. Reusing an
        existing marker with the same reason prevents a long-running snapshot
        build from being requeued every minute. A newer production upload has a
        different reason and safely replaces the older marker.
        """
        year, month = int(year), int(month)
        target = cls._path(year, month)
        if target.exists():
            try:
                existing = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                existing = None
            if (
                isinstance(existing, dict)
                and int(existing.get("year") or 0) == year
                and int(existing.get("month") or 0) == month
                and str(existing.get("reason") or "") == str(reason)
            ):
                return existing

        payload = {
            "year": year,
            "month": month,
            "reason": str(reason),
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }
        temporary = target.with_suffix(f".json.tmp-{os.getpid()}")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, target)
        return payload

    @classmethod
    def dependency_periods(cls, year: int, month: int) -> list[tuple[int, int]]:
        """Return completed IMS periods that depend on one finalized production month."""
        year, month = int(year), int(month)
        candidate_years = [year] if month != 12 else [year, year + 1]
        rows = (
            IMSUpload.query.with_entities(IMSUpload.year, IMSUpload.month)
            .filter(
                IMSUpload.status == IMSUpload.STATUS_COMPLETED,
                IMSUpload.year.in_(candidate_years),
            )
            .all()
        )
        periods = {
            (int(row[0]), int(row[1]))
            for row in rows
            if (
                int(row[0]) == year
                and int(row[1]) >= month
            ) or (
                month == 12
                and int(row[0]) == year + 1
                and int(row[1]) == 1
            )
        }
        return sorted(periods)

    @classmethod
    def enqueue_for_production(
        cls, year: int, month: int, production_upload_id: int
    ) -> list[dict]:
        """Refresh every already-open snapshot period affected by production.

        Example: when July production arrives in September, July, August and
        September are all rebuilt. July becomes the final monthly authority;
        August/September are rebuilt because Q3/YTD/AI comparisons include July.
        """
        reason = f"production_upload:{int(production_upload_id)}"
        return [
            cls.enqueue(target_year, target_month, reason=reason)
            for target_year, target_month in cls.dependency_periods(year, month)
        ]

    @classmethod
    def _dashboard_quota_is_current(cls, year: int, month: int, payload: dict) -> bool:
        """Verify persisted national quota rows against current allocated targets."""
        from app.services.production_result_service import ProductionResultService

        quota = ProductionResultService.quota_product_months([(int(year), int(month))])
        quota_ids = {
            int(product_id)
            for product_id, periods in quota.items()
            if (int(year), int(month)) in periods
        }
        if not quota_ids:
            return True

        allocated = dict(
            db.session.query(
                Target.product_id,
                sa.func.coalesce(sa.func.sum(Target.tl_target), 0.0),
            )
            .filter(
                Target.year == int(year),
                Target.month == int(month),
                Target.product_id.in_(quota_ids),
            )
            .group_by(Target.product_id)
            .all()
        )
        rows = ((payload or {}).get("executive_metrics") or {}).get("products") or []
        by_product = {
            int(row.get("product_id") or 0): row
            for row in rows
            if int(row.get("product_id") or 0) in quota_ids
        }
        for product_id in quota_ids:
            expected = round(float(allocated.get(product_id) or 0), 2)
            if expected <= 0:
                continue
            row = by_product.get(product_id)
            if row is None:
                return False
            if (
                round(float(row.get("target_tl") or 0), 2) != expected
                or round(float(row.get("actual_tl") or 0), 2) != expected
            ):
                return False
        return True

    @classmethod
    def _period_is_fresh_for_production(
        cls, year: int, month: int, *, cutoff
    ) -> bool:
        """Check all durable read models for one production dependency cutoff."""
        from app.services.persistent_dashboard_snapshot_service import (
            PersistentDashboardSnapshotService,
        )
        from app.services.persistent_region_snapshot_service import (
            PersistentRegionSnapshotService,
            region_snapshot_sets,
        )
        from app.services.persistent_representative_snapshot_service import (
            PersistentRepresentativeSnapshotService,
            representative_snapshot_sets,
        )

        year, month = int(year), int(month)
        ims_id, production_id = PersistentDashboardSnapshotService.source_identity(
            year, month
        )
        if not ims_id:
            return True

        if not PersistentDashboardSnapshotService.generation_ready(
            year, month, ims_id, production_id
        ):
            return False
        try:
            envelope = json.loads(
                PersistentDashboardSnapshotService._generation_path(
                    year, month, ims_id, production_id
                ).read_text(encoding="utf-8")
            )
        except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
            return False
        dashboard_payload = envelope.get("payload") or {}
        if not cls._dashboard_quota_is_current(year, month, dashboard_payload):
            return False
        dashboard_created = cls._naive_utc(envelope.get("created_at"))

        region_row = db.session.execute(
            sa.select(
                region_snapshot_sets.c.id,
                region_snapshot_sets.c.region_count,
                region_snapshot_sets.c.created_at,
                region_snapshot_sets.c.activated_at,
            )
            .where(
                region_snapshot_sets.c.year == year,
                region_snapshot_sets.c.month == month,
                region_snapshot_sets.c.source_upload_id == int(ims_id),
                region_snapshot_sets.c.production_upload_id == int(production_id),
                region_snapshot_sets.c.status
                == PersistentRegionSnapshotService.STATUS_ACTIVE,
            )
            .order_by(
                region_snapshot_sets.c.activated_at.desc(),
                region_snapshot_sets.c.id.desc(),
            )
            .limit(1)
        ).first()
        if region_row is None:
            return False
        region_payloads = PersistentRegionSnapshotService._payloads_from_set(
            int(region_row.id)
        )
        if (
            not region_payloads
            or len(region_payloads) != int(region_row.region_count or 0)
            or any(
                int((payload or {}).get("read_model_version") or 0)
                < PersistentRegionSnapshotService.READ_MODEL_VERSION
                or not isinstance((payload or {}).get("ai_report"), dict)
                for payload in region_payloads.values()
            )
        ):
            return False
        region_created = cls._naive_utc(
            region_row.activated_at or region_row.created_at
        )

        representative_row = db.session.execute(
            sa.select(
                representative_snapshot_sets.c.id,
                representative_snapshot_sets.c.representative_count,
                representative_snapshot_sets.c.created_at,
                representative_snapshot_sets.c.activated_at,
            )
            .where(
                representative_snapshot_sets.c.year == year,
                representative_snapshot_sets.c.month == month,
                representative_snapshot_sets.c.source_upload_id == int(ims_id),
                representative_snapshot_sets.c.production_upload_id
                == int(production_id),
                representative_snapshot_sets.c.status
                == PersistentRepresentativeSnapshotService.STATUS_ACTIVE,
            )
            .order_by(
                representative_snapshot_sets.c.activated_at.desc(),
                representative_snapshot_sets.c.id.desc(),
            )
            .limit(1)
        ).first()
        if (
            representative_row is None
            or int(representative_row.representative_count or 0) <= 0
            or PersistentRepresentativeSnapshotService._set_read_model_version(
                int(representative_row.id)
            )
            < PersistentRepresentativeSnapshotService.READ_MODEL_VERSION
        ):
            return False
        representative_created = cls._naive_utc(
            representative_row.activated_at or representative_row.created_at
        )

        cutoff = cls._naive_utc(cutoff)
        if cutoff is None:
            return True
        return all(
            created is not None and created >= cutoff
            for created in (
                dashboard_created,
                region_created,
                representative_created,
            )
        )

    @classmethod
    def enqueue_stale_production_dependencies(cls) -> list[dict]:
        """Self-heal missed/old production refreshes without manual maintenance."""
        from app.services.production_result_service import ProductionResultService

        periods = (
            db.session.query(
                ProductionResultUpload.year,
                ProductionResultUpload.month,
            )
            .filter(
                ProductionResultUpload.status
                == ProductionResultUpload.STATUS_APPLIED
            )
            .distinct()
            .order_by(
                ProductionResultUpload.year.asc(),
                ProductionResultUpload.month.asc(),
            )
            .all()
        )
        queued = []
        for year, month in periods:
            final = ProductionResultService.final_upload(int(year), int(month))
            if final is None:
                continue
            cutoff = final.applied_at or final.uploaded_at
            reason = f"production_upload:{int(final.id)}"
            for target_year, target_month in cls.dependency_periods(year, month):
                target_cutoff = cls._dependency_cutoff(
                    year, month, target_year, target_month, cutoff
                )
                if cls._period_is_fresh_for_production(
                    target_year, target_month, cutoff=target_cutoff
                ):
                    continue
                queued.append(
                    cls.enqueue(target_year, target_month, reason=reason)
                )
        return queued

    @staticmethod
    def _production_priority(payload: dict) -> int:
        """Newest production upload wins; mtime rotates peers after failures."""
        reason = str(payload.get("reason") or "")
        prefix = "production_upload:"
        if not reason.startswith(prefix):
            return 0
        try:
            return int(reason[len(prefix):])
        except (TypeError, ValueError):
            return 0

    @classmethod
    def next(cls) -> dict | None:
        candidates = []
        for path in cls._root().glob("????-??.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["_path"] = str(path)
                candidates.append(
                    (
                        -cls._production_priority(payload),
                        path.stat().st_mtime,
                        path.name,
                        payload,
                    )
                )
            except (OSError, ValueError, json.JSONDecodeError):
                path.unlink(missing_ok=True)
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[:3])
        return candidates[0][3]

    @classmethod
    def defer(cls, item: dict) -> None:
        """Keep a failed marker durable but move it behind pending periods."""
        path = Path(str(item.get("_path") or ""))
        if not path:
            return
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
            return
        if (
            str(current.get("requested_at") or "")
            == str(item.get("requested_at") or "")
            and str(current.get("reason") or "")
            == str(item.get("reason") or "")
        ):
            os.utime(path, None)

    @classmethod
    def complete(cls, item: dict) -> None:
        """Delete only the exact marker that was actually processed.

        If a newer production upload replaced the same period marker while the
        worker was busy, leave the newer request in place for the next loop.
        """
        path = Path(str(item.get("_path") or ""))
        if not path:
            return
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
            return
        if (
            str(current.get("requested_at") or "")
            == str(item.get("requested_at") or "")
            and str(current.get("reason") or "")
            == str(item.get("reason") or "")
        ):
            path.unlink(missing_ok=True)
