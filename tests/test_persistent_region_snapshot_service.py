from pathlib import Path
import tempfile

import pytest

from app import create_app
from app.extensions import db
from app.services import persistent_region_snapshot_service as snapshot_module
from app.services.persistent_region_snapshot_service import (
    PersistentRegionSnapshotService,
    region_snapshot_sets,
)


class Config:
    TESTING = True
    SECRET_KEY = "persistent-region-snapshot"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = Path(tempfile.gettempdir()) / "persistent-region-snapshot-uploads"
    REPORT_FOLDER = Path(tempfile.gettempdir()) / "persistent-region-snapshot-reports"
    BACKUP_FOLDER = Path(tempfile.gettempdir()) / "persistent-region-snapshot-backups"
    LOG_FOLDER = Path(tempfile.gettempdir()) / "persistent-region-snapshot-logs"


def _app():
    app = create_app(Config)
    with app.app_context():
        db.create_all()
    return app


class FakePerformance:
    def __init__(self, region_key, year, month):
        self.region_key = str(region_key)
        self.year = year
        self.month = month
        self.rep_ids = [1]

    def report(self):
        return {
            "region_key": self.region_key,
            "region_name": f"Region {self.region_key}",
            "year": self.year,
            "month": self.month,
            "periods": {
                "monthly": {
                    "source_by_month": {(self.year, self.month): "OFFICIAL_REGION_SUBTOTAL"}
                }
            },
            "annual_realization": [],
        }


class FakeMarket:
    def __init__(self, region_key, representative_ids, year, month):
        self.region_key = region_key

    def build(self):
        return {"has_data": True, "region": self.region_key}


def _patch_sources(monkeypatch, identity):
    monkeypatch.setattr(
        PersistentRegionSnapshotService,
        "source_identity",
        classmethod(lambda cls, year, month: identity),
    )
    monkeypatch.setattr(
        PersistentRegionSnapshotService,
        "region_keys",
        classmethod(lambda cls, year, month: ["101", "102"]),
    )
    monkeypatch.setattr(snapshot_module, "RegionPerformanceService", FakePerformance)
    monkeypatch.setattr(snapshot_module, "RegionMarketService", FakeMarket)


def test_complete_set_is_persisted_and_reused(monkeypatch):
    app = _app()
    with app.app_context():
        _patch_sources(monkeypatch, (17, 0))
        progress = []
        result = PersistentRegionSnapshotService.build_for_period(
            2026, 4, progress=lambda done, total, name: progress.append((done, total, name))
        )

        assert result["status"] == "ACTIVE"
        assert result["regions"] == 2
        assert [item[:2] for item in progress] == [(1, 2), (2, 2)]
        payload = PersistentRegionSnapshotService.get_active("102", 2026, 4)
        assert payload["report"]["region_key"] == "102"
        assert payload["market_analysis"]["region"] == "102"
        assert payload["report"]["periods"]["monthly"]["source_by_month"] == {
            "2026|4": "OFFICIAL_REGION_SUBTOTAL"
        }

        fast_payload = PersistentRegionSnapshotService.get_active_for_visible_upload(
            "102", 2026, 4, 17
        )
        assert fast_payload["report"]["region_key"] == "102"
        assert PersistentRegionSnapshotService.get_active_for_visible_upload(
            "102", 2026, 4, 999
        ) is None

        pack = PersistentRegionSnapshotService.get_active_all(2026, 4)
        assert set(pack) == {"101", "102"}
        assert pack["101"]["report"]["region_key"] == "101"
        assert pack["102"]["market_analysis"]["region"] == "102"

        reused = PersistentRegionSnapshotService.build_for_period(2026, 4)
        assert reused["status"] == "REUSED"
        assert reused["set_id"] == result["set_id"]


def test_previous_active_stays_visible_while_new_generation_is_building(monkeypatch):
    app = _app()
    with app.app_context():
        _patch_sources(monkeypatch, (17, 0))
        first = PersistentRegionSnapshotService.build_for_period(2026, 4)
        assert first["status"] == "ACTIVE"

        monkeypatch.setattr(
            PersistentRegionSnapshotService,
            "source_identity",
            classmethod(lambda cls, year, month: (18, 0)),
        )
        result = db.session.execute(region_snapshot_sets.insert().values(
            year=2026,
            month=4,
            source_upload_id=18,
            production_upload_id=0,
            status=PersistentRegionSnapshotService.STATUS_BUILDING,
            region_count=0,
        ))
        building_id = int(result.inserted_primary_key[0])
        db.session.commit()

        visible = PersistentRegionSnapshotService.get_active("101", 2026, 4)
        assert visible["report"]["region_key"] == "101"
        pack = PersistentRegionSnapshotService.get_active_all(2026, 4)
        assert set(pack) == {"101", "102"}

        db.session.execute(
            region_snapshot_sets.update().where(region_snapshot_sets.c.id == building_id).values(
                status=PersistentRegionSnapshotService.STATUS_FAILED
            )
        )
        db.session.commit()
        assert PersistentRegionSnapshotService.get_active("101", 2026, 4) is None
        assert PersistentRegionSnapshotService.get_active_all(2026, 4) == {}


def test_failed_new_build_never_supersedes_previous_active(monkeypatch):
    app = _app()
    with app.app_context():
        _patch_sources(monkeypatch, (17, 0))
        first = PersistentRegionSnapshotService.build_for_period(2026, 4)
        assert first["status"] == "ACTIVE"

        monkeypatch.setattr(
            PersistentRegionSnapshotService,
            "source_identity",
            classmethod(lambda cls, year, month: (18, 0)),
        )

        class FailingPerformance(FakePerformance):
            def report(self):
                if self.region_key == "102":
                    raise RuntimeError("simulated snapshot failure")
                return super().report()

        monkeypatch.setattr(snapshot_module, "RegionPerformanceService", FailingPerformance)
        try:
            PersistentRegionSnapshotService.build_for_period(2026, 4)
            raise AssertionError("snapshot build should fail")
        except RuntimeError as exc:
            assert "simulated snapshot failure" in str(exc)

        rows = db.session.execute(
            region_snapshot_sets.select().where(
                region_snapshot_sets.c.year == 2026,
                region_snapshot_sets.c.month == 4,
            )
        ).all()
        statuses = {row.source_upload_id: row.status for row in rows}
        assert statuses[17] == PersistentRegionSnapshotService.STATUS_ACTIVE
        assert statuses[18] == PersistentRegionSnapshotService.STATUS_FAILED



def test_late_production_keeps_same_ims_region_visible_until_replacement(monkeypatch):
    app = _app()
    identity = {"value": (44, 8)}
    with app.app_context():
        _patch_sources(monkeypatch, identity["value"])
        monkeypatch.setattr(
            PersistentRegionSnapshotService,
            "source_identity",
            classmethod(lambda cls, year, month: identity["value"]),
        )
        first = PersistentRegionSnapshotService.build_for_period(2026, 7)
        assert first["status"] == "ACTIVE"

        identity["value"] = (44, 9)
        visible = PersistentRegionSnapshotService.get_active("101", 2026, 7)
        assert visible is not None
        assert visible["report"]["region_key"] == "101"

        replacement = PersistentRegionSnapshotService.build_for_period(2026, 7)
        assert replacement["status"] == "ACTIVE"
        assert replacement["set_id"] != first["set_id"]


def test_force_refresh_replaces_same_identity_active_set(monkeypatch):
    app = _app()
    with app.app_context():
        _patch_sources(monkeypatch, (17, 5))
        first = PersistentRegionSnapshotService.build_for_period(2026, 7)
        assert first["status"] == "ACTIVE"
        before = PersistentRegionSnapshotService.get_active("101", 2026, 7)
        assert before["report"]["region_name"] == "Region 101"

        class RefreshedPerformance(FakePerformance):
            def report(self):
                payload = super().report()
                payload["region_name"] = f"Final {self.region_key}"
                return payload

        monkeypatch.setattr(
            snapshot_module, "RegionPerformanceService", RefreshedPerformance
        )
        refreshed = PersistentRegionSnapshotService.build_for_period(
            2026, 7, force=True
        )
        assert refreshed["status"] == "ACTIVE"
        assert refreshed["forced"] is True
        assert refreshed["set_id"] == first["set_id"]

        after = PersistentRegionSnapshotService.get_active("101", 2026, 7)
        assert after["report"]["region_name"] == "Final 101"
        rows = db.session.execute(
            region_snapshot_sets.select().where(
                region_snapshot_sets.c.year == 2026,
                region_snapshot_sets.c.month == 7,
                region_snapshot_sets.c.source_upload_id == 17,
                region_snapshot_sets.c.production_upload_id == 5,
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].status == PersistentRegionSnapshotService.STATUS_ACTIVE


def test_failed_force_refresh_keeps_previous_active_payload(monkeypatch):
    app = _app()
    with app.app_context():
        _patch_sources(monkeypatch, (17, 5))
        first = PersistentRegionSnapshotService.build_for_period(2026, 7)
        assert first["status"] == "ACTIVE"
        before = PersistentRegionSnapshotService.get_active("101", 2026, 7)

        class FailingRefresh(FakePerformance):
            def report(self):
                if self.region_key == "102":
                    raise RuntimeError("late production refresh failed")
                payload = super().report()
                payload["region_name"] = f"Candidate {self.region_key}"
                return payload

        monkeypatch.setattr(snapshot_module, "RegionPerformanceService", FailingRefresh)
        with pytest.raises(RuntimeError, match="late production refresh failed"):
            PersistentRegionSnapshotService.build_for_period(
                2026, 7, force=True
            )

        after = PersistentRegionSnapshotService.get_active("101", 2026, 7)
        assert after == before
