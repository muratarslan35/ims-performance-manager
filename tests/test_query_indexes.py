from pathlib import Path

import pytest
from flask_migrate import upgrade
from sqlalchemy import text


MIGRATIONS_DIR = str(Path(__file__).resolve().parents[1] / "migrations")


@pytest.fixture()
def indexed_app(tmp_path):
    from app import create_app

    class TestConfig:
        TESTING = True
        SECRET_KEY = "query-index-test"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'query-index.db'}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = tmp_path / "uploads"
        REPORT_FOLDER = tmp_path / "reports"
        BACKUP_FOLDER = tmp_path / "backups"
        LOG_FOLDER = tmp_path / "logs"
        TEMP_FOLDER = tmp_path / "temp"

    application = create_app(TestConfig)
    with application.app_context():
        upgrade(directory=MIGRATIONS_DIR)
    yield application

    with application.app_context():
        from app.extensions import db

        db.session.remove()


def _plan_details(db, sql, parameters):
    rows = db.session.execute(text(f"EXPLAIN QUERY PLAN {sql}"), parameters).all()
    return "\n".join(str(row[-1]) for row in rows)


def test_raw_dashboard_read_uses_upload_sheet_type_index(indexed_app):
    from app.extensions import db

    with indexed_app.app_context():
        plan = _plan_details(
            db,
            "SELECT id, product_id, unit, tl FROM ims_raw_data "
            "WHERE upload_id = :upload_id AND sheet_type = :sheet_type",
            {"upload_id": 1, "sheet_type": "dashboard_balance_region"},
        )

    assert "ix_ims_raw_upload_sheet_type" in plan


def test_competition_dashboard_read_uses_metric_flags_index(indexed_app):
    from app.extensions import db

    with indexed_app.app_context():
        plan = _plan_details(
            db,
            "SELECT territory, product_group, SUM(metric_value) "
            "FROM ims_competition_data "
            "WHERE upload_id = :upload_id AND metric_type = :metric_type "
            "AND is_subtotal = 0 AND is_grand_total = 0 "
            "GROUP BY territory, product_group",
            {"upload_id": 1, "metric_type": "TL"},
        )

    assert "ix_competition_upload_metric_flags" in plan
