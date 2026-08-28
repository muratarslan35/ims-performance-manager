import tempfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import event


def _test_app():
    from app import create_app

    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "dashboard-competition.db"

    class TestConfig:
        TESTING = True
        SECRET_KEY = "dashboard-competition-test"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        LOGIN_DISABLED = True
        UPLOAD_FOLDER = Path(temp_dir.name) / "uploads"
        REPORT_FOLDER = Path(temp_dir.name) / "reports"
        BACKUP_FOLDER = Path(temp_dir.name) / "backups"
        LOG_FOLDER = Path(temp_dir.name) / "logs"
        TEMP_FOLDER = Path(temp_dir.name) / "temp"

    return create_app(TestConfig), temp_dir


def _competition_row(upload_id, *, metric_value):
    from app.models import CompetitionData

    return CompetitionData(
        upload_id=upload_id,
        year=2026,
        month=2,
        week_number=1,
        sheet_name=f"competition-{upload_id}",
        period_type="WEEKLY",
        territory="901 DIYARBAKIR",
        subterritory="DIYARBAKIR",
        product_group="TEST GROUP",
        product_name="TEST PRODUCT",
        metric_type="TL",
        metric_value=metric_value,
        is_subtotal=False,
        is_grand_total=False,
        source_row=1,
    )


def test_latest_competition_upload_uses_exists_and_is_memoized_per_request():
    app, temp_dir = _test_app()
    try:
        with app.app_context():
            from app.extensions import db
            from app.models import IMSUpload
            from app.query.dashboard_query import DashboardQuery
            from app.query.filters import DashboardFilterParams

            db.create_all()
            older_with_data = IMSUpload(
                file_name="week-7.xlsx", year=2026, month=2, week_number=7,
                status="COMPLETED", completed_at=datetime(2026, 2, 20),
            )
            newer_zero_only = IMSUpload(
                file_name="week-8-zero.xlsx", year=2026, month=2, week_number=8,
                status="COMPLETED", completed_at=datetime(2026, 2, 27),
            )
            failed_newer = IMSUpload(
                file_name="week-9-failed.xlsx", year=2026, month=2, week_number=9,
                status="FAILED", completed_at=datetime(2026, 2, 28),
            )
            db.session.add_all([older_with_data, newer_zero_only, failed_newer])
            db.session.flush()
            db.session.add_all([
                _competition_row(older_with_data.id, metric_value=125.0),
                _competition_row(newer_zero_only.id, metric_value=0.0),
                _competition_row(failed_newer.id, metric_value=900.0),
            ])
            db.session.commit()

            statements = []
            def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
                statements.append(statement)

            event.listen(db.engine, "before_cursor_execute", before_cursor_execute)
            try:
                query = DashboardQuery()
                filters = DashboardFilterParams(year=2026, month=2)
                resolved = query._latest_competition_upload_id(filters)
                first_query_count = len(statements)
                resolved_again = query._latest_competition_upload_id(filters)
            finally:
                event.remove(db.engine, "before_cursor_execute", before_cursor_execute)

            assert resolved == older_with_data.id
            assert resolved_again == older_with_data.id
            assert first_query_count == 1
            assert len(statements) == first_query_count
            normalized_sql = " ".join(statements[0].upper().split())
            assert "EXISTS" in normalized_sql
            assert "JOIN IMS_COMPETITION_DATA" not in normalized_sql
            assert "GROUP BY" not in normalized_sql
    finally:
        temp_dir.cleanup()
