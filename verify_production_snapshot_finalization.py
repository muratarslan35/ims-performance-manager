"""Wait for every late-production dependency to publish fresh read models.

This verifier is intentionally read-model focused. It never recalculates business
rows itself; it only asks the durable production-refresh queue to reconcile
missing/stale dependencies and waits for the single IMS worker to publish them.
"""
from __future__ import annotations

import argparse
import time

from app import create_app
from app.extensions import db
from app.models import ProductionResultUpload
from app.services.production_result_service import ProductionResultService
from app.services.representative_snapshot_refresh_queue import (
    RepresentativeSnapshotRefreshQueue,
)


def _final_sources():
    periods = (
        db.session.query(
            ProductionResultUpload.year,
            ProductionResultUpload.month,
        )
        .filter(
            ProductionResultUpload.status == ProductionResultUpload.STATUS_APPLIED
        )
        .distinct()
        .order_by(
            ProductionResultUpload.year.asc(),
            ProductionResultUpload.month.asc(),
        )
        .all()
    )
    result = []
    for year, month in periods:
        final = ProductionResultService.final_upload(int(year), int(month))
        if final is not None:
            result.append(final)
    return result


def _stale_dependencies():
    stale = []
    for source in _final_sources():
        cutoff = source.applied_at or source.uploaded_at
        for year, month in RepresentativeSnapshotRefreshQueue.dependency_periods(
            source.year, source.month
        ):
            if RepresentativeSnapshotRefreshQueue._period_is_fresh_for_production(
                year, month, cutoff=cutoff
            ):
                continue
            stale.append(
                (
                    int(source.id),
                    int(source.year),
                    int(source.month),
                    int(year),
                    int(month),
                )
            )
    return stale


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait-seconds", type=int, default=1200)
    parser.add_argument("--poll-seconds", type=int, default=5)
    args = parser.parse_args()

    app = create_app()
    deadline = time.monotonic() + max(0, int(args.wait_seconds))
    attempts = 0
    with app.app_context():
        while True:
            attempts += 1
            queued = RepresentativeSnapshotRefreshQueue.enqueue_stale_production_dependencies()
            stale = _stale_dependencies()
            db.session.remove()

            if not stale:
                sources = _final_sources()
                source_text = ",".join(
                    f"{int(item.year):04d}-{int(item.month):02d}:P{int(item.production_stage)}#{int(item.id)}"
                    for item in sources
                ) or "none"
                print(
                    "PRODUCTION_FINALIZATION|status=PASS|"
                    f"sources={source_text}|attempts={attempts}|queued={len(queued)}"
                )
                return 0

            if time.monotonic() >= deadline:
                stale_text = ",".join(
                    (
                        f"source#{source_id}:{source_year:04d}-{source_month:02d}"
                        f"->target:{target_year:04d}-{target_month:02d}"
                    )
                    for (
                        source_id,
                        source_year,
                        source_month,
                        target_year,
                        target_month,
                    ) in stale
                )
                print(
                    "PRODUCTION_FINALIZATION|status=FAIL|"
                    f"attempts={attempts}|stale={stale_text}"
                )
                return 1

            time.sleep(max(1, int(args.poll_seconds)))


if __name__ == "__main__":
    raise SystemExit(main())
