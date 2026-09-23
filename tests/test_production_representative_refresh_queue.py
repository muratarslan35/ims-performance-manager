import json
import os
from pathlib import Path

from app.services.representative_snapshot_refresh_queue import (
    RepresentativeSnapshotRefreshQueue,
)


def test_production_refresh_queue_contract():
    queue_source = Path("app/services/representative_snapshot_refresh_queue.py").read_text(
        encoding="utf-8"
    )
    ims_source = Path("app/ims.py").read_text(encoding="utf-8")
    retry_source = Path("app/services/production_result_retry_ui.py").read_text(
        encoding="utf-8"
    )
    worker = Path("ims_import_worker.py").read_text(encoding="utf-8")

    assert "enqueue_for_production" in queue_source
    assert "dependency_periods" in queue_source
    assert "enqueue_stale_production_dependencies" in queue_source
    assert "ProductionResultUpload.STATUS_APPLIED" in queue_source
    assert "requested_at" in queue_source
    assert "def defer(cls, item: dict)" in queue_source
    assert "def _production_priority(payload: dict)" in queue_source
    assert "-cls._production_priority(payload)" in queue_source
    assert "os.utime(path, None)" in queue_source
    assert "RepresentativeSnapshotRefreshQueue.enqueue_for_production" in ims_source
    assert "RepresentativeSnapshotRefreshQueue.enqueue_for_production" in retry_source
    assert "_process_representative_refresh_queue" in worker
    assert "representative_refresh_queue_started year=%s month=%s reason=%s" in worker
    assert "dashboard_result = _warm_dashboard_snapshot(app, year, month, force=True)" in worker
    assert "region_result = _warm_region_snapshots(app, year, month, force=True)" in worker
    assert "_warm_representative_snapshots(" in worker
    assert "app, year, month, force=True" in worker
    assert "PersistentRegionSnapshotService.enrich_for_period(year, month)" in worker
    assert "enqueue_stale_production_dependencies" in worker

    refresh_worker = worker[worker.index("def _process_representative_refresh_queue(app):") :]
    dashboard = refresh_worker.index(
        "dashboard_result = _warm_dashboard_snapshot(app, year, month, force=True)"
    )
    representative = refresh_worker.index(
        "representative_result = _warm_representative_snapshots("
    )
    region = refresh_worker.index(
        "region_result = _warm_region_snapshots(app, year, month, force=True)"
    )
    enrichment = refresh_worker.index(
        "PersistentRegionSnapshotService.enrich_for_period(year, month)", region
    )
    force_path = refresh_worker.index(
        "dashboard_result = _warm_dashboard_snapshot(app, year, month, force=True)"
    )
    completion = refresh_worker.index(
        "RepresentativeSnapshotRefreshQueue.complete(item)", max(enrichment, force_path)
    )
    assert force_path == dashboard
    assert dashboard < representative < region < enrichment < completion
    assert 'region_result.get("status") in {"ACTIVE", "REUSED"}' in refresh_worker
    assert 'enrichment_result.get("status") in {"ENRICHED", "REUSED"}' in refresh_worker
    assert "RepresentativeSnapshotRefreshQueue.defer(item)" in refresh_worker

    # IMS/publication remains first in the single worker loop; refresh work is
    # only examined when no IMS job was claimed.
    idle = worker.index("if job is None:")
    reconcile = worker.index("enqueue_stale_production_dependencies", idle)
    refresh = worker.index("_process_representative_refresh_queue(app)", idle)
    process_job = worker.index("IMSImportQueue.process(job)", idle)
    assert reconcile < refresh < process_job



def test_newest_production_upload_has_priority_and_failed_peer_rotates(tmp_path, monkeypatch):
    monkeypatch.setattr(
        RepresentativeSnapshotRefreshQueue,
        "_root",
        classmethod(lambda cls: tmp_path),
    )

    def write_marker(name, *, year, month, reason, requested_at, mtime):
        path = tmp_path / name
        path.write_text(
            json.dumps(
                {
                    "year": year,
                    "month": month,
                    "reason": reason,
                    "requested_at": requested_at,
                }
            ),
            encoding="utf-8",
        )
        os.utime(path, (mtime, mtime))

    write_marker(
        "2026-01.json",
        year=2026,
        month=1,
        reason="production_upload:1",
        requested_at="2026-01-01T00:00:00+00:00",
        mtime=1,
    )
    write_marker(
        "2026-07.json",
        year=2026,
        month=7,
        reason="production_upload:9",
        requested_at="2026-09-22T00:00:00+00:00",
        mtime=2,
    )
    write_marker(
        "2026-08.json",
        year=2026,
        month=8,
        reason="production_upload:9",
        requested_at="2026-09-22T00:00:01+00:00",
        mtime=3,
    )

    first = RepresentativeSnapshotRefreshQueue.next()
    assert first is not None
    assert first["reason"] == "production_upload:9"
    assert first["month"] == 7

    RepresentativeSnapshotRefreshQueue.defer(first)
    second = RepresentativeSnapshotRefreshQueue.next()
    assert second is not None
    assert second["reason"] == "production_upload:9"
    assert second["month"] == 8


# deploy.yml is intentionally covered by the repo's locked-contract approval gate.
def test_late_production_cascade_contract():
    queue_source = Path("app/services/representative_snapshot_refresh_queue.py").read_text(
        encoding="utf-8"
    )
    region_source = Path("app/services/persistent_region_snapshot_service.py").read_text(
        encoding="utf-8"
    )
    worker = Path("ims_import_worker.py").read_text(encoding="utf-8")

    # Same-year completed IMS periods at/after the finalized month are dependent.
    assert "int(row[0]) == year" in queue_source
    assert "int(row[1]) >= month" in queue_source
    # December production also changes the following January comparison.
    assert "month == 12" in queue_source
    assert "int(row[0]) == year + 1" in queue_source
    assert "int(row[1]) == 1" in queue_source

    # Downstream periods cannot be treated as REUSED merely because their own
    # IMS/production identity is unchanged.
    assert "force: bool = False" in region_source
    assert "existing_complete and not force" in region_source
    assert "existing_complete and force" in region_source
    assert "replacement_rows" in region_source
    assert "PersistentDashboardSnapshotService.publish(year, month, _payload)" in worker


def test_source_production_month_uses_exact_identity_and_downstream_keeps_cutoff():
    cutoff = object()

    assert RepresentativeSnapshotRefreshQueue._dependency_cutoff(
        2026, 7, 2026, 7, cutoff
    ) is None
    assert RepresentativeSnapshotRefreshQueue._dependency_cutoff(
        2026, 7, 2026, 8, cutoff
    ) is cutoff
    assert RepresentativeSnapshotRefreshQueue._dependency_cutoff(
        2026, 12, 2027, 1, cutoff
    ) is cutoff

    queue_source = Path("app/services/representative_snapshot_refresh_queue.py").read_text(
        encoding="utf-8"
    )
    verifier = Path("verify_production_snapshot_finalization.py").read_text(
        encoding="utf-8"
    )
    assert "target_cutoff = cls._dependency_cutoff(" in queue_source
    assert verifier.count(
        "target_cutoff = RepresentativeSnapshotRefreshQueue._dependency_cutoff("
    ) == 2


def test_worker_discards_already_fresh_production_marker_before_force_rebuild():
    worker = Path("ims_import_worker.py").read_text(encoding="utf-8")
    refresh = worker[worker.index("def _process_representative_refresh_queue(app):") :]

    assert "def _queued_production_refresh_is_fresh(item, year, month):" in worker
    assert "ProductionResultUpload.STATUS_APPLIED" in worker
    assert "RepresentativeSnapshotRefreshQueue._dependency_cutoff(" in worker
    assert "RepresentativeSnapshotRefreshQueue._period_is_fresh_for_production(" in worker
    fresh = refresh.index("_queued_production_refresh_is_fresh(item, year, month)")
    complete = refresh.index("RepresentativeSnapshotRefreshQueue.complete(item)", fresh)
    force_dashboard = refresh.index(
        "dashboard_result = _warm_dashboard_snapshot(app, year, month, force=True)"
    )
    assert fresh < complete < force_dashboard
    assert "already_fresh=1" in refresh


def test_worker_completes_missing_region_enrichment_before_force_rebuild():
    worker = Path("ims_import_worker.py").read_text(encoding="utf-8")
    region = Path("app/services/persistent_region_snapshot_service.py").read_text(
        encoding="utf-8"
    )
    refresh = worker[worker.index("def _process_representative_refresh_queue(app):") :]

    enrich = refresh.index(
        "preflight_enrichment = PersistentRegionSnapshotService.enrich_for_period(year, month)"
    )
    second_fresh = refresh.index(
        "_queued_production_refresh_is_fresh(item, year, month)", enrich
    )
    complete = refresh.index("RepresentativeSnapshotRefreshQueue.complete(item)", second_fresh)
    force_representatives = refresh.index(
        "representative_result = _warm_representative_snapshots(", complete
    )
    assert enrich < second_fresh < complete < force_representatives
    assert "already_fresh_after_enrichment=1" in refresh
    assert 'and isinstance((payload or {}).get("ai_report"), dict)' in region
