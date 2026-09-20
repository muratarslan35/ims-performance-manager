from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import pytest

from app.services.report_cache_service import ReportCacheService
from app.services.report_export_queue import ReportExportQueue


@pytest.fixture()
def cache_app(tmp_path):
    from flask import Flask

    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        REPORT_CACHE_FOLDER=tmp_path / "report_cache",
        REPORT_EXPORT_QUEUE_FOLDER=tmp_path / "report_export_queue",
    )
    return app


class DummyService:
    year = 2026
    month = 9
    period = "monthly"
    scope = "region"
    scope_value = "901 DIYARBAKIR"
    product_ids = set()

    def __init__(self, counter, lock):
        self.counter = counter
        self.lock = lock

    def months(self):
        return [(2026, 9)]

    @staticmethod
    def _region_code(value):
        return "901"

    @staticmethod
    def _scope_key(value):
        return str(value).upper()

    def build(self):
        with self.lock:
            self.counter["builds"] += 1
        return {
            "year": 2026,
            "month": 9,
            "period": "monthly",
            "scope": "region",
            "scope_label": "Diyarbakır",
            "rows": [],
            "totals": {},
            "trend": [],
            "rival_rows": [],
            "representative_count": 0,
            "source_week": 37,
        }


def test_report_cache_singleflight_builds_once_for_concurrent_users(cache_app, monkeypatch):
    monkeypatch.setattr(
        ReportCacheService,
        "source_sets",
        classmethod(lambda cls, service: [{"year": 2026, "month": 9, "set_id": 2517}]),
    )
    counter = {"builds": 0}
    lock = threading.Lock()

    def read_once(_index):
        with cache_app.app_context():
            report, key, built = ReportCacheService.get_or_build(DummyService(counter, lock))
            return report["scope_label"], key, built

    with ThreadPoolExecutor(max_workers=24) as pool:
        rows = list(pool.map(read_once, range(200)))

    assert counter["builds"] == 1
    assert len({row[1] for row in rows}) == 1
    assert sum(1 for row in rows if row[2]) == 1
    assert {row[0] for row in rows} == {"Diyarbakır"}


def test_cache_key_changes_with_snapshot_generation(cache_app, monkeypatch):
    source = {"set_id": 2517}

    def source_sets(cls, service):
        return [{"year": 2026, "month": 9, "set_id": source["set_id"]}]

    monkeypatch.setattr(ReportCacheService, "source_sets", classmethod(source_sets))
    counter = {"builds": 0}
    lock = threading.Lock()

    with cache_app.app_context():
        first = ReportCacheService.identity(DummyService(counter, lock))[0]
        source["set_id"] = 2518
        second = ReportCacheService.identity(DummyService(counter, lock))[0]

    assert first != second


def test_export_queue_deduplicates_identical_artifact_requests(cache_app):
    with cache_app.app_context():
        first = ReportExportQueue.enqueue(
            cache_key="abc123",
            file_type="pdf",
            filename="bolge-analiz-raporu-diyarbakir-2026-09.pdf",
            scope="region",
            scope_value="901",
        )
        second = ReportExportQueue.enqueue(
            cache_key="abc123",
            file_type="pdf",
            filename="bolge-analiz-raporu-diyarbakir-2026-09.pdf",
            scope="region",
            scope_value="901",
        )
        assert first["job_id"] == second["job_id"]
        assert ReportExportQueue.position(first["job_id"]) == 1
        assert len(list((Path(cache_app.config["REPORT_EXPORT_QUEUE_FOLDER"]) / "jobs").glob("*.json"))) == 1


def test_report_worker_isolated_and_resource_bounded_contract():
    root = Path(__file__).resolve().parents[1]
    worker = (root / "report_export_worker.py").read_text(encoding="utf-8")
    unit = (root / "deploy" / "ims-report-worker.service.in").read_text(encoding="utf-8")
    installer = (root / "deploy" / "install_systemd_service.sh").read_text(encoding="utf-8")
    routes = (root / "app" / "routes" / "__init__.py").read_text(encoding="utf-8")
    deploy = (root / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    js = (root / "app" / "static" / "js" / "executive-reports.js").read_text(encoding="utf-8")

    assert "ReportCacheService.get_or_build(service)" in routes
    assert "ReportExportQueue.enqueue(" in routes
    assert "status===202" in js
    assert "pollExport" in js

    assert "_ims_busy()" in worker
    assert "User-triggered exports always outrank speculative prewarming." in worker
    assert "ReportCacheService.cached_export" in worker

    assert "ExecStart=@IMS_PATH@/venv/bin/python @IMS_PATH@/report_export_worker.py" in unit
    assert "Nice=12" in unit
    assert "CPUWeight=500" in unit
    assert "MemoryHigh=350M" in unit
    assert "MemoryMax=450M" in unit

    assert "ims-report-worker.service" in installer
    assert 'systemctl enable "$report_worker_service_name"' in installer
    assert "REPORT_WORKER_ACTIVE|" in deploy
    assert "Report worker health check passed." in deploy
