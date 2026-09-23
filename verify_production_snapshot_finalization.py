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
from app.models import ProductionResultUpload, User
from app.services.persistent_region_snapshot_service import (
    PersistentRegionSnapshotService,
)
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


def _latest_applied_source(sources):
    if not sources:
        return None
    return max(
        sources,
        key=lambda item: (
            item.applied_at or item.uploaded_at,
            int(item.id),
        ),
    )


def _selected_sources(*, latest_source_only: bool):
    sources = _final_sources()
    if not latest_source_only:
        return sources
    latest = _latest_applied_source(sources)
    return [latest] if latest is not None else []


def _stale_dependencies(sources, *, source_period_only: bool = False):
    stale = []
    for source in sources:
        cutoff = source.applied_at or source.uploaded_at
        periods = (
            [(int(source.year), int(source.month))]
            if source_period_only
            else RepresentativeSnapshotRefreshQueue.dependency_periods(
                source.year, source.month
            )
        )
        for year, month in periods:
            target_cutoff = RepresentativeSnapshotRefreshQueue._dependency_cutoff(
                source.year, source.month, year, month, cutoff
            )
            if RepresentativeSnapshotRefreshQueue._period_is_fresh_for_production(
                year, month, cutoff=target_cutoff
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


def _enqueue_stale_sources(sources):
    queued = []
    for source in sources:
        cutoff = source.applied_at or source.uploaded_at
        reason = f"production_upload:{int(source.id)}"
        for year, month in RepresentativeSnapshotRefreshQueue.dependency_periods(
            source.year, source.month
        ):
            target_cutoff = RepresentativeSnapshotRefreshQueue._dependency_cutoff(
                source.year, source.month, year, month, cutoff
            )
            if RepresentativeSnapshotRefreshQueue._period_is_fresh_for_production(
                year, month, cutoff=target_cutoff
            ):
                continue
            queued.append(
                RepresentativeSnapshotRefreshQueue.enqueue(
                    year, month, reason=reason
                )
            )
    return queued


def _historical_region_route_check(app, sources):
    if not sources:
        return "none"
    # Prefer the oldest finalized period because delayed production normally
    # targets history. Any prepared region key is sufficient for route readiness.
    source = sources[0]
    regions = PersistentRegionSnapshotService.get_active_all(
        int(source.year), int(source.month)
    )
    if not regions:
        raise RuntimeError(
            f"No active region snapshot for {int(source.year):04d}-{int(source.month):02d}"
        )
    region_key = sorted(regions)[0]
    admin = User.query.filter(
        db.func.lower(User.email) == "admin@ipm.local"
    ).one_or_none()
    if admin is None:
        raise RuntimeError("Production finalization route verifier needs admin@ipm.local")

    client = app.test_client()
    app.login_manager.session_protection = None
    with client.session_transaction() as session:
        session["_user_id"] = str(admin.id)
        session["_fresh"] = True
        session["portal"] = "manager"
    path = (
        f"/regions/{region_key}?year={int(source.year)}&month={int(source.month)}"
    )
    response = client.get(path, follow_redirects=False)
    if response.status_code != 200:
        raise RuntimeError(
            f"Historical region route is not ready: path={path} status={response.status_code}"
        )
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait-seconds", type=int, default=1200)
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument(
        "--latest-source-only",
        action="store_true",
        help=(
            "Verify the source month of the most recently applied finalized "
            "production upload. Downstream Q/YTD dependencies remain queued in "
            "background; omit this flag for a full historical audit."
        ),
    )
    args = parser.parse_args()

    app = create_app()
    deadline = time.monotonic() + max(0, int(args.wait_seconds))
    attempts = 0
    with app.app_context():
        while True:
            attempts += 1
            sources = _selected_sources(
                latest_source_only=bool(args.latest_source_only)
            )
            if args.latest_source_only:
                queued = _enqueue_stale_sources(sources)
            else:
                queued = (
                    RepresentativeSnapshotRefreshQueue
                    .enqueue_stale_production_dependencies()
                )
            stale = _stale_dependencies(
                sources,
                source_period_only=bool(args.latest_source_only),
            )
            db.session.remove()

            if not stale:
                source_text = ",".join(
                    f"{int(item.year):04d}-{int(item.month):02d}:P{int(item.production_stage)}#{int(item.id)}"
                    for item in sources
                ) or "none"
                route = _historical_region_route_check(app, sources)
                print(
                    "PRODUCTION_FINALIZATION|status=PASS|"
                    f"sources={source_text}|attempts={attempts}|queued={len(queued)}|"
                    f"historical_route={route}"
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
