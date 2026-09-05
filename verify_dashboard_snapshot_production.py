"""Production acceptance for the durable national dashboard snapshot.

This verifier never rebuilds dashboard business data. It waits for the import
worker/startup warm-up to publish a snapshot whose IMS and production source
identity matches the active dashboard period, then measures repeated reads of
that already-published snapshot. Production deploys can therefore fail closed
when the shared cross-worker dashboard read model is not actually ready.
"""
from __future__ import annotations

import argparse
import statistics
import time

from app import create_app
from app.services.dashboard_service import DashboardService
from app.services.persistent_dashboard_snapshot_service import PersistentDashboardSnapshotService


def _percentile95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * 0.95 + 0.999999)))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait-seconds", type=float, default=120.0)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--reads", type=int, default=5)
    parser.add_argument("--max-read-seconds", type=float, default=2.0)
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        service = DashboardService()
        year, month = int(service.year), int(service.month)
        expected_ims_id, expected_production_id = PersistentDashboardSnapshotService.source_identity(year, month)
        deadline = time.monotonic() + max(0.0, args.wait_seconds)
        attempts = 0
        while True:
            attempts += 1
            payload = PersistentDashboardSnapshotService.get_active(year, month)
            if isinstance(payload, dict) and payload:
                break
            if time.monotonic() >= deadline:
                print("DASHBOARD_SNAPSHOT_ACCEPTANCE|status=FAIL|reason=not_ready|" f"year={year}|month={month}|ims_upload_id={expected_ims_id}|" f"production_upload_id={expected_production_id}|attempts={attempts}")
                return 1
            time.sleep(max(0.05, args.poll_seconds))

        read_times = []
        for _ in range(max(1, args.reads)):
            started = time.perf_counter()
            ready = PersistentDashboardSnapshotService.get_active(year, month)
            elapsed = time.perf_counter() - started
            if not isinstance(ready, dict) or not ready:
                print("DASHBOARD_SNAPSHOT_ACCEPTANCE|status=FAIL|reason=became_unavailable|" f"year={year}|month={month}|ims_upload_id={expected_ims_id}|" f"production_upload_id={expected_production_id}")
                return 1
            read_times.append(elapsed)

        actual_ims_id, actual_production_id = PersistentDashboardSnapshotService.source_identity(year, month)
        p95 = _percentile95(read_times)
        mean = statistics.fmean(read_times)
        if (actual_ims_id, actual_production_id) != (expected_ims_id, expected_production_id):
            print("DASHBOARD_SNAPSHOT_ACCEPTANCE|status=FAIL|reason=source_changed|" f"year={year}|month={month}|expected_ims_upload_id={expected_ims_id}|" f"actual_ims_upload_id={actual_ims_id}|expected_production_upload_id={expected_production_id}|" f"actual_production_upload_id={actual_production_id}")
            return 1
        if p95 > args.max_read_seconds:
            print("DASHBOARD_SNAPSHOT_ACCEPTANCE|status=FAIL|reason=slow_read|" f"year={year}|month={month}|ims_upload_id={actual_ims_id}|" f"production_upload_id={actual_production_id}|reads={len(read_times)}|" f"read_p95_seconds={p95:.4f}|read_mean_seconds={mean:.4f}|" f"max_read_seconds={args.max_read_seconds:.4f}")
            return 1

        print("DASHBOARD_SNAPSHOT_ACCEPTANCE|status=PASS|" f"year={year}|month={month}|ims_upload_id={actual_ims_id}|" f"production_upload_id={actual_production_id}|reads={len(read_times)}|" f"read_p95_seconds={p95:.4f}|read_mean_seconds={mean:.4f}|attempts={attempts}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
