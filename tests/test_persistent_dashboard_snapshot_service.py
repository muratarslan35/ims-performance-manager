from pathlib import Path

from flask import Flask

from app.services.persistent_dashboard_snapshot_service import PersistentDashboardSnapshotService


def test_snapshot_is_shared_and_rejected_when_source_identity_changes(tmp_path, monkeypatch):
    app = Flask(__name__, instance_path=str(tmp_path / "instance"))
    identity = {"value": (32, 7)}
    monkeypatch.setattr(
        PersistentDashboardSnapshotService,
        "source_identity",
        classmethod(lambda cls, year, month: identity["value"]),
    )

    with app.app_context():
        payload = {"overall_percent": 81.4, "nested": {"tuple_key": {(2026, 4): "IMS"}}}
        result = PersistentDashboardSnapshotService.publish(2026, 4, payload)
        assert result["status"] == "ACTIVE"
        assert result["ims_upload_id"] == 32

        loaded = PersistentDashboardSnapshotService.get_active(2026, 4)
        assert loaded["overall_percent"] == 81.4
        assert loaded["nested"]["tuple_key"] == {"2026|4": "IMS"}

        identity["value"] = (33, 7)
        assert PersistentDashboardSnapshotService.get_active(2026, 4) is None


def test_dashboard_route_prefers_durable_snapshot_before_orchestrator():
    source = Path("app/dashboard.py").read_text(encoding="utf-8")
    assert "PersistentDashboardSnapshotService.get_active" in source
    get_pos = source.index("PersistentDashboardSnapshotService.get_active")
    run_pos = source.index("payload = service.run()")
    assert get_pos < run_pos
    assert "DashboardCache().invalidate(cache_key)" in source


def test_worker_warms_dashboard_after_successful_import_and_startup_backfill():
    source = Path("ims_import_worker.py").read_text(encoding="utf-8")
    assert "def _warm_dashboard_snapshot" in source
    assert "PersistentDashboardSnapshotService.publish" in source
    assert "completed.status == IMSImportJob.STATUS_COMPLETED" in source
    assert "_warm_dashboard_snapshot(app, latest.year, latest.month)" in source
