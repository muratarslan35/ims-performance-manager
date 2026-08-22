from datetime import datetime, timedelta
from pathlib import Path

from app import create_app
from app.extensions import db
from app.models import IMSRawData, IMSUpload
from app.services.official_aggregate_service import OfficialAggregateService, TARGET_TYPE
from app.services.period_service import PeriodService


class SnapshotSelectionConfig:
    TESTING = True
    SECRET_KEY = "snapshot-selection-test"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = Path("/tmp/snapshot-selection-uploads")
    REPORT_FOLDER = Path("/tmp/snapshot-selection-reports")
    BACKUP_FOLDER = Path("/tmp/snapshot-selection-backups")
    LOG_FOLDER = Path("/tmp/snapshot-selection-logs")


def test_latest_week_wins_over_later_replay_timestamp():
    app = create_app(SnapshotSelectionConfig)
    with app.app_context():
        db.create_all()
        now = datetime.utcnow()
        week_five = IMSUpload(
            file_name="5.Hafta.xlsx", year=2026, month=1, week_number=5,
            status="COMPLETED", completed_at=now,
        )
        replayed_week_three = IMSUpload(
            file_name="3.Hafta.xlsx", year=2026, month=1, week_number=3,
            status="COMPLETED", completed_at=now + timedelta(days=1),
        )
        db.session.add_all([week_five, replayed_week_three])
        db.session.flush()
        db.session.add_all([
            IMSRawData(upload_id=week_five.id, year=2026, month=1, quarter="Q1", week_number=5,
                       sheet_name="BAKİYE", sheet_type=TARGET_TYPE, source_row=0, territory="901",
                       product_id=1, tl=11882910.93, unit=1, raw_json="{}"),
            IMSRawData(upload_id=replayed_week_three.id, year=2026, month=1, quarter="Q1", week_number=3,
                       sheet_name="BAKİYE", sheet_type=TARGET_TYPE, source_row=0, territory="901",
                       product_id=1, tl=9413862.43, unit=1, raw_json="{}"),
        ])
        db.session.commit()

        assert PeriodService.get_active_period()["week_number"] == 5
        assert OfficialAggregateService.latest_upload_id(2026, 1, TARGET_TYPE) == week_five.id
