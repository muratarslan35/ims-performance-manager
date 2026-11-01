import json
from pathlib import Path

import pytest
from sqlalchemy import event

from app import create_app
from app.extensions import db
from app.models import CompetitionData, IMSUpload
from app.cache.ims_generation_reads import isolated_generation_reads
from app.cache import region_period_catalog as catalog
from app.services.region_market_service import RegionMarketService


@pytest.fixture
def catalog_context(tmp_path):
    class Config:
        TESTING = True
        SECRET_KEY = "period-catalog-test"
        SQLALCHEMY_DATABASE_URI = "sqlite://"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        UPLOAD_FOLDER = tmp_path / "uploads"
        REPORT_FOLDER = tmp_path / "reports"
        BACKUP_FOLDER = tmp_path / "backups"
        LOG_FOLDER = tmp_path / "logs"
        REGION_PERIOD_CATALOG_CACHE_ENABLED = True

    app = create_app(Config)
    app.instance_path = str(tmp_path / "instance")
    with app.app_context():
        db.create_all()
        september = IMSUpload(file_name="old.xlsx", year=2026, month=9, status="COMPLETED")
        october = IMSUpload(file_name="new.xlsx", year=2026, month=10, status="COMPLETED")
        pending = IMSUpload(file_name="pending.xlsx", year=2026, month=8, status="PENDING")
        db.session.add_all([september, october, pending]); db.session.flush()

        def add(upload, territory, metric="UNIT"):
            # Period authority belongs to IMSUpload, not a competition label.
            row = CompetitionData(upload_id=upload.id, year=2020, month=1,
                                  sheet_name="SOURCE", period_type="MONTHLY", territory=territory,
                                  subterritory=territory, product_group="GROUP", product_name="PRODUCT",
                                  metric_type=metric, metric_value=0, is_subtotal=True, source_row=1)
            db.session.add(row)

        add(september, "1010 BRICK"); add(september, "101 REGION"); add(september, "901 REGION")
        add(october, "602 REGION"); add(october, "NATIONAL"); add(october, "901 REGION", "TL")
        add(pending, "101 REGION")
        db.session.commit()
        queries = []

        def capture(conn, cursor, statement, parameters, context, many):
            if "FROM ims_competition_data" in statement:
                queries.append((statement, parameters))

        event.listen(db.engine, "before_cursor_execute", capture)
        try:
            yield app, september, october, queries, add
        finally:
            event.remove(db.engine, "before_cursor_execute", capture)
            db.session.remove()


def _periods(code):
    return RegionMarketService(code, [], 2026, 10)._available_periods()


def test_catalog_matches_legacy_exists_and_reuses_only_unchanged_metadata(catalog_context):
    app, september, october, queries, add = catalog_context
    expected = {code: _periods(code) for code in ("101", "901", "602")}
    queries.clear()
    with isolated_generation_reads():
        assert {code: _periods(code) for code in expected} == expected
        assert len(queries) == 1
        assert catalog.generation_region_periods("10") is None
        assert catalog.generation_region_periods("１０１") is None
    queries.clear()
    with isolated_generation_reads():
        assert {code: _periods(code) for code in expected} == expected
        assert not queries
    assert catalog.generation_region_periods("101") is None
    assert _periods("101") == expected["101"]  # ordinary callers retain legacy lookup


def test_new_upload_rescans_changed_month_without_scanning_historical_uploads(catalog_context):
    app, september, october, queries, add = catalog_context
    catalog.load_period_catalog()
    october.status = "ROLLED_BACK"
    replacement = IMSUpload(file_name="replacement.xlsx", year=2026, month=10, status="COMPLETED")
    db.session.add(replacement); db.session.flush(); add(replacement, "901 NEW")
    db.session.commit(); queries.clear()
    actual = catalog.load_period_catalog()
    assert actual[(2026, 9)] == {"101", "901"}
    assert actual[(2026, 10)] == {"901"}
    # The first two binds are substr(territory, 1, 3), the final bind is UNIT.
    assert len(queries) == 1 and queries[0][1][2:-1] == (replacement.id,)


def test_corrupt_code_changed_or_unwritable_metadata_falls_back_to_source(catalog_context, monkeypatch):
    app, september, october, queries, add = catalog_context
    expected = catalog.load_period_catalog()
    path = Path(app.instance_path) / "region_period_catalog" / "2026-10.json"
    data = json.loads(path.read_text()); data["regions"] = ["999"]
    path.write_text(json.dumps(data)); queries.clear()
    assert catalog.load_period_catalog() == expected
    assert len(queries) == 1
    monkeypatch.setattr(catalog, "_code_revision", lambda root: "changed-code")
    queries.clear()
    assert catalog.load_period_catalog() == expected and len(queries) == 1
    monkeypatch.setattr(catalog, "_code_revision", lambda root: "next-code")

    def denied(*args, **kwargs):
        raise OSError("cache storage unavailable")

    monkeypatch.setattr(catalog.os, "open", denied)
    assert catalog.load_period_catalog() == expected
