"""Verify and atomically finalize the latest IMS snapshot publication.

The script is safe to run during deploy. It never publishes a partially built
generation: dashboard, region, representative and enriched region read models
must all match the latest IMS source before the one publication marker is set.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sqlalchemy as sa

from app import create_app
from app.extensions import db
from app.models import IMSImportJob, IMSUpload
from app.services.ims_progress_store import IMSProgressStore
from app.services.persistent_dashboard_snapshot_service import (
    PersistentDashboardSnapshotService,
)
from app.services.persistent_region_snapshot_service import (
    PersistentRegionSnapshotService,
)
from app.services.persistent_representative_snapshot_service import (
    PersistentRepresentativeSnapshotService,
    representative_snapshots,
)


def _final_progress(job) -> tuple[bool, dict, dict]:
    progress = IMSProgressStore.read(job.id) or {}
    try:
        summary = json.loads(job.result_summary or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        summary = {}
    complete = bool(
        progress.get("status") == IMSImportJob.STATUS_COMPLETED
        and progress.get("stage") == "completed"
        and int(progress.get("percent") or 0) == 100
    )
    return complete, progress, summary


def main() -> int:
    app = create_app()
    with app.app_context():
        latest = (
            IMSUpload.query.filter_by(status=IMSUpload.STATUS_COMPLETED)
            .order_by(
                IMSUpload.year.desc(),
                IMSUpload.month.desc(),
                IMSUpload.week_number.desc(),
                IMSUpload.completed_at.desc(),
                IMSUpload.id.desc(),
            )
            .first()
        )
        if latest is None:
            print("LATEST_SNAPSHOT_FINALIZE|SKIPPED|reason=no_completed_ims")
            return 0

        job = (
            IMSImportJob.query.filter_by(ims_upload_id=int(latest.id))
            .order_by(IMSImportJob.id.desc())
            .first()
        )
        if job is None:
            print(
                "LATEST_SNAPSHOT_FINALIZE|SKIPPED|reason=no_linked_job"
                f"|upload_id={int(latest.id)}"
            )
            return 0

        final_progress, progress, summary = _final_progress(job)
        if not final_progress:
            print(
                "LATEST_SNAPSHOT_FINALIZE|SKIPPED|reason=snapshot_work_in_progress"
                f"|job_id={int(job.id)}|stage={progress.get('stage') or '-'}"
                f"|percent={int(progress.get('percent') or 0)}"
            )
            return 0

        other_active = IMSImportJob.query.filter(
            IMSImportJob.id != int(job.id),
            IMSImportJob.status.in_(
                (IMSImportJob.STATUS_QUEUED, IMSImportJob.STATUS_PROCESSING)
            ),
        ).first()
        if other_active is not None:
            raise RuntimeError(
                f"Another IMS job is active while finalizing publication: {other_active.id}"
            )

        year, month = int(latest.year), int(latest.month)
        ims_id, production_id = PersistentDashboardSnapshotService.source_identity(
            year, month
        )
        if int(ims_id or 0) != int(latest.id):
            raise RuntimeError(
                f"Latest snapshot source mismatch: expected={latest.id} actual={ims_id}"
            )

        if not PersistentDashboardSnapshotService.generation_ready(
            year, month, ims_id, production_id
        ):
            raise RuntimeError("Latest dashboard generation is not ready.")

        region_set = PersistentRegionSnapshotService._existing_set(
            year, month, ims_id, production_id
        )
        expected_regions = len(PersistentRegionSnapshotService.region_keys(year, month))
        region_rows = (
            PersistentRegionSnapshotService._payloads_from_set(region_set.id)
            if region_set is not None
            else {}
        )
        if (
            region_set is None
            or region_set.status != PersistentRegionSnapshotService.STATUS_ACTIVE
            or expected_regions <= 0
            or len(region_rows) != expected_regions
        ):
            raise RuntimeError(
                "Latest region generation is incomplete: "
                f"status={getattr(region_set, 'status', None)} "
                f"rows={len(region_rows)} expected={expected_regions}"
            )

        expected_representatives = (
            PersistentRepresentativeSnapshotService.representative_ids(
                year, month, ims_id
            )
        )
        representative_set = (
            PersistentRepresentativeSnapshotService._latest_exact_active(
                year, month, ims_id, production_id
            )
        )
        representative_rows = (
            int(
                db.session.execute(
                    sa.select(sa.func.count())
                    .select_from(representative_snapshots)
                    .where(
                        representative_snapshots.c.set_id
                        == int(representative_set.id)
                    )
                ).scalar()
                or 0
            )
            if representative_set is not None
            else 0
        )
        if (
            representative_set is None
            or not expected_representatives
            or representative_rows != len(expected_representatives)
            or int(representative_set.representative_count or 0)
            != len(expected_representatives)
        ):
            raise RuntimeError(
                "Latest representative generation is incomplete: "
                f"rows={representative_rows} "
                f"expected={len(expected_representatives)}"
            )

        result = PersistentRegionSnapshotService.enrich_for_period(year, month)
        if result.get("status") not in {"ENRICHED", "REUSED"}:
            raise RuntimeError(f"Latest region enrichment is not ready: {result}")

        enriched = PersistentRegionSnapshotService._payloads_from_set(region_set.id)
        if len(enriched) != expected_regions or not all(
            int((payload or {}).get("read_model_version") or 0)
            >= PersistentRegionSnapshotService.READ_MODEL_VERSION
            for payload in enriched.values()
        ):
            raise RuntimeError("Latest region generation is not fully enriched.")

        # This commit is the single visibility switch for the new IMS generation.
        attached = db.session.get(IMSImportJob, int(job.id))
        if attached is None:
            raise RuntimeError("IMS publication job disappeared during finalization.")
        try:
            summary = json.loads(attached.result_summary or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            summary = {}
        summary["publication_ready"] = True
        summary["publication_ready_upload_id"] = int(latest.id)
        summary["publication_ready_source"] = "verified_atomic_snapshot_finalizer"
        attached.result_summary = json.dumps(summary, ensure_ascii=False)
        attached.error_message = None
        db.session.commit()

        IMSProgressStore.write(
            attached.id,
            percent=100,
            stage="completed",
            message="IMS yüklemesi ve tüm ekran snapshotları hazır",
            detail=(
                f"Dashboard hazır · Bölge {expected_regions}/{expected_regions} · "
                f"Temsilci {len(expected_representatives)}/{len(expected_representatives)}"
            ),
            status=IMSImportJob.STATUS_COMPLETED,
        )

        print(
            "LATEST_SNAPSHOT_FINALIZE|PASS"
            f"|year={year}|month={month}|week={int(latest.week_number or 0)}"
            f"|upload_id={int(latest.id)}|regions={expected_regions}"
            f"|representatives={len(expected_representatives)}"
            f"|repaired={int(summary.get('publication_ready_source') == 'verified_atomic_snapshot_finalizer')}"
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
