from pathlib import Path

from flask import Flask
from types import SimpleNamespace

import pytest

from app.services.persistent_dashboard_snapshot_service import PersistentDashboardSnapshotService


@pytest.fixture(autouse=True)
def no_pending_publication(monkeypatch):
    from app.services.ims_publication_service import IMSPublicationService

    monkeypatch.setattr(
        IMSPublicationService,
        "pending_job",
        classmethod(lambda cls, year=None, month=None: None),
    )



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


def test_late_production_keeps_same_ims_dashboard_visible_until_replacement(tmp_path, monkeypatch):
    app = Flask(__name__, instance_path=str(tmp_path / "instance"))
    identity = {"value": (44, 8)}
    monkeypatch.setattr(
        PersistentDashboardSnapshotService,
        "source_identity",
        classmethod(lambda cls, year, month: identity["value"]),
    )

    with app.app_context():
        PersistentDashboardSnapshotService.publish(2026, 7, {"production": 8})
        identity["value"] = (44, 9)

        assert PersistentDashboardSnapshotService.get_active(2026, 7) == {
            "production": 8
        }

        PersistentDashboardSnapshotService.publish(2026, 7, {"production": 9})
        assert PersistentDashboardSnapshotService.get_active(2026, 7) == {
            "production": 9
        }


def test_get_or_build_executes_builder_once_for_same_source(tmp_path, monkeypatch):
    app = Flask(__name__, instance_path=str(tmp_path / "instance"))
    monkeypatch.setattr(
        PersistentDashboardSnapshotService,
        "source_identity",
        classmethod(lambda cls, year, month: (32, 7)),
    )
    calls = {"count": 0}

    def builder():
        calls["count"] += 1
        return {"overall_percent": 77.0}

    with app.app_context():
        first, first_built = PersistentDashboardSnapshotService.get_or_build(2026, 4, builder)
        second, second_built = PersistentDashboardSnapshotService.get_or_build(2026, 4, builder)

    assert first == second == {"overall_percent": 77.0}
    assert first_built is True
    assert second_built is False
    assert calls["count"] == 1


def test_previous_dashboard_generation_is_reused_after_source_rollback(tmp_path, monkeypatch):
    app = Flask(__name__, instance_path=str(tmp_path / "instance"))
    identity = {"value": (31, 0)}
    monkeypatch.setattr(
        PersistentDashboardSnapshotService,
        "source_identity",
        classmethod(lambda cls, year, month: identity["value"]),
    )

    with app.app_context():
        PersistentDashboardSnapshotService.publish(2026, 4, {"week": 16})
        identity["value"] = (32, 0)
        PersistentDashboardSnapshotService.publish(2026, 4, {"week": 17})
        identity["value"] = (31, 0)

        assert PersistentDashboardSnapshotService.get_active(2026, 4) == {"week": 16}


def test_dashboard_route_uses_cross_worker_get_or_build():
    source = Path("app/dashboard.py").read_text(encoding="utf-8")
    assert "PersistentDashboardSnapshotService.get_active" in source
    assert "pending is None" in source
    assert "DashboardCache().invalidate(cache_key)" in source
    assert "return service.run()" in source


def test_worker_warms_dashboard_after_successful_import_and_startup_backfill():
    source = Path("ims_import_worker.py").read_text(encoding="utf-8")
    assert "def _warm_dashboard_snapshot" in source
    assert "PersistentDashboardSnapshotService.get_generation_for_source" in source
    assert "PersistentDashboardSnapshotService.publish" in source
    assert "completed.status == IMSImportJob.STATUS_COMPLETED" in source
    assert "_warm_dashboard_snapshot(app, latest.year, latest.month)" in source

def test_pending_publication_keeps_previous_dashboard_generation_visible(tmp_path, monkeypatch):
    from app.services.ims_publication_service import IMSPublicationService

    app = Flask(__name__, instance_path=str(tmp_path / "instance"))
    identity = {"value": (31, 0)}
    monkeypatch.setattr(
        PersistentDashboardSnapshotService,
        "source_identity",
        classmethod(lambda cls, year, month: identity["value"]),
    )

    with app.app_context():
        PersistentDashboardSnapshotService.publish(2026, 9, {"week": 37})
        identity["value"] = (32, 0)
        PersistentDashboardSnapshotService.publish(2026, 9, {"week": 38})

        monkeypatch.setattr(
            IMSPublicationService,
            "pending_job",
            classmethod(lambda cls, year=None, month=None: SimpleNamespace(id=99)),
        )
        monkeypatch.setattr(
            IMSPublicationService,
            "latest_visible_upload",
            classmethod(
                lambda cls, year=None, month=None: SimpleNamespace(
                    id=31, year=2026, month=9, week_number=37
                )
            ),
        )

        assert PersistentDashboardSnapshotService.get_active(2026, 9) == {"week": 37}
        assert PersistentDashboardSnapshotService.get_generation_for_source(
            2026, 9, 32, 0
        ) == {"week": 38}


def test_user_facing_dashboard_and_market_routes_do_not_bypass_publication_gate():
    dashboard = Path("app/dashboard.py").read_text(encoding="utf-8")
    routes = Path("app/routes/__init__.py").read_text(encoding="utf-8")

    assert "PersistentDashboardSnapshotService.get_stable" not in dashboard
    market_start = routes.index("def market_analysis():")
    market_end = routes.index(
        '@main_bp.route("/market-analysis/regions-pack")', market_start
    )
    market_route = routes[market_start:market_end]
    assert "PersistentDashboardSnapshotService.get_stable" not in market_route

