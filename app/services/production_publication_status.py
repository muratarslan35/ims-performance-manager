"""Truthful publication progress for production-result uploads.

``APPLIED`` means that the validated workbook is authoritative in the business
tables.  It does not mean that every persisted Dashboard/representative/region
read model has been rebuilt.  This service keeps those two states separate so
the IMS screen can only say "Tamamlandı" after every affected period is ready.
"""
from __future__ import annotations

import json

import sqlalchemy as sa

from app.extensions import db
from app.models import ProductionResultUpload
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
from app.services.production_result_service import ProductionResultService
from app.services.representative_snapshot_refresh_queue import (
    RepresentativeSnapshotRefreshQueue,
)


class ProductionPublicationStatus:
    @staticmethod
    def _fresh(value, cutoff) -> bool:
        value = RepresentativeSnapshotRefreshQueue._naive_utc(value)
        cutoff = RepresentativeSnapshotRefreshQueue._naive_utc(cutoff)
        return value is not None and (cutoff is None or value >= cutoff)

    @classmethod
    def _dashboard_ready(cls, year, month, ims_id, production_id, cutoff):
        if not PersistentDashboardSnapshotService.generation_ready(
            year, month, ims_id, production_id
        ):
            return False
        try:
            payload = json.loads(
                PersistentDashboardSnapshotService._generation_path(
                    year, month, ims_id, production_id
                ).read_text(encoding="utf-8")
            )
        except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return False
        return cls._fresh(payload.get("created_at"), cutoff)

    @classmethod
    def _period(cls, source, year, month):
        year, month = int(year), int(month)
        ims_id, production_id = PersistentDashboardSnapshotService.source_identity(
            year, month
        )
        if not ims_id:
            return {
                "year": year, "month": month, "ready": True, "percent": 100,
                "stage": "Atlandı", "detail": "Bu dönem için tamamlanmış IMS bulunmuyor.",
            }

        cutoff = RepresentativeSnapshotRefreshQueue._dependency_cutoff(
            source.year,
            source.month,
            year,
            month,
            source.applied_at or source.uploaded_at,
        )
        dashboard_ready = cls._dashboard_ready(
            year, month, ims_id, production_id, cutoff
        )
        expected_representatives = len(
            PersistentRepresentativeSnapshotService.representative_ids(
                year, month, ims_id
            )
        )

        representative = db.session.execute(
            sa.select(
                representative_snapshot_sets.c.status,
                representative_snapshot_sets.c.representative_count,
                representative_snapshot_sets.c.created_at,
                representative_snapshot_sets.c.activated_at,
            ).where(
                representative_snapshot_sets.c.year == year,
                representative_snapshot_sets.c.month == month,
                representative_snapshot_sets.c.source_upload_id == int(ims_id),
                representative_snapshot_sets.c.production_upload_id == int(production_id),
            ).order_by(representative_snapshot_sets.c.id.desc()).limit(1)
        ).first()
        representative_count = min(
            int(representative.representative_count or 0) if representative else 0,
            expected_representatives,
        )
        representative_ready = bool(
            representative
            and representative.status
            == PersistentRepresentativeSnapshotService.STATUS_ACTIVE
            and representative_count == expected_representatives
            and cls._fresh(
                representative.activated_at or representative.created_at, cutoff
            )
        )

        region = db.session.execute(
            sa.select(
                region_snapshot_sets.c.status,
                region_snapshot_sets.c.region_count,
                region_snapshot_sets.c.created_at,
                region_snapshot_sets.c.activated_at,
            ).where(
                region_snapshot_sets.c.year == year,
                region_snapshot_sets.c.month == month,
                region_snapshot_sets.c.source_upload_id == int(ims_id),
                region_snapshot_sets.c.production_upload_id == int(production_id),
            ).order_by(region_snapshot_sets.c.id.desc()).limit(1)
        ).first()
        region_count = int(region.region_count or 0) if region else 0
        region_ready = bool(
            region
            and region.status == PersistentRegionSnapshotService.STATUS_ACTIVE
            and region_count > 0
            and cls._fresh(region.activated_at or region.created_at, cutoff)
        )

        # Weight the long representative build by its real member count.  The
        # smaller dashboard and region layers retain visible, truthful steps.
        representative_fraction = (
            representative_count / max(expected_representatives, 1)
        )
        percent = round(
            (10 if dashboard_ready else 0)
            + 75 * representative_fraction
            + (10 if region_ready else 0)
        )

        if not dashboard_ready:
            stage = "Dashboard hazırlanıyor"
            detail = f"{year}/{month:02d} Dashboard snapshotı oluşturuluyor."
        elif not representative_ready:
            stage = "Temsilci ekranları hazırlanıyor"
            detail = (
                f"{year}/{month:02d} · {representative_count}/"
                f"{expected_representatives} temsilci hazır"
            )
        elif not region_ready:
            stage = "Bölge ekranları hazırlanıyor"
            detail = f"{year}/{month:02d} · {region_count or 0} bölge hazır"
        else:
            stage = "Son doğrulama"
            detail = f"{year}/{month:02d} snapshot bütünlüğü doğrulanıyor."

        quick_ready = dashboard_ready and representative_ready and region_ready
        ready = bool(
            quick_ready
            and RepresentativeSnapshotRefreshQueue._period_is_fresh_for_production(
                year, month, cutoff=cutoff
            )
        )
        if ready:
            percent, stage = 100, "Hazır"
            detail = (
                f"{year}/{month:02d} · {expected_representatives} temsilci ve "
                f"{region_count} bölge hazır"
            )
        return {
            "year": year,
            "month": month,
            "ready": ready,
            "percent": max(0, min(percent, 100)),
            "stage": stage,
            "detail": detail,
            "representatives_done": representative_count,
            "representatives_total": expected_representatives,
            "regions_done": region_count,
        }

    @classmethod
    def describe(cls, upload: ProductionResultUpload) -> dict:
        if upload.status == ProductionResultUpload.STATUS_FAILED:
            return {
                "active": False, "status": "FAILED", "percent": 0,
                "message": "Üretim dosyası uygulanamadı",
                "detail": upload.error_message or "Doğrulama başarısız.",
                "periods": [],
            }
        if upload.status != ProductionResultUpload.STATUS_APPLIED:
            message = (
                "Üretim dosyası doğrulanıyor"
                if upload.status == ProductionResultUpload.STATUS_PENDING_VALIDATION
                else "Üretim verileri uygulanıyor"
            )
            return {
                "active": True, "status": "PROCESSING", "percent": 8,
                "message": message,
                "detail": "Excel şablonu, temsilciler ve ürünler kontrol ediliyor.",
                "periods": [],
            }

        final = ProductionResultService.final_upload(upload.year, upload.month)
        if final is not None and int(final.id) != int(upload.id):
            return {
                "active": False, "status": "SUPERSEDED", "percent": 100,
                "message": "Daha yeni üretim sonucu geçerli",
                "detail": f"{final.production_stage}. üretim dosyası aktif.",
                "periods": [],
            }

        periods = [
            cls._period(upload, year, month)
            for year, month in RepresentativeSnapshotRefreshQueue.dependency_periods(
                upload.year, upload.month
            )
        ]
        if not periods:
            return {
                "active": False, "status": "COMPLETED", "percent": 100,
                "message": "Üretim dosyası tamamlandı",
                "detail": "Güncellenecek açık IMS dönemi bulunmuyor.",
                "periods": [],
            }

        ready_count = sum(1 for item in periods if item["ready"])
        current = next((item for item in periods if not item["ready"]), periods[-1])
        # Workbook validation/application owns the first 15%; affected read
        # models share the remaining 85% according to measured snapshot state.
        percent = round(15 + 85 * sum(item["percent"] for item in periods) / (100 * len(periods)))
        completed = ready_count == len(periods)
        return {
            "active": not completed,
            "status": "COMPLETED" if completed else "PROCESSING",
            "percent": 100 if completed else min(percent, 99),
            "message": (
                "Üretim dosyası tamamlandı"
                if completed else current["stage"]
            ),
            "detail": (
                f"{len(periods)}/{len(periods)} dönem güncellendi."
                if completed
                else f"{ready_count}/{len(periods)} dönem hazır · {current['detail']}"
            ),
            "periods": periods,
        }
