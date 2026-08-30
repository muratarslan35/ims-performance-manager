from datetime import datetime
from pathlib import Path

import pytest

from app import create_app


def _app(tmp_path):
    class Config:
        TESTING = True
        SECRET_KEY = "ims-roster-sync"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'roster.db'}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        LOGIN_DISABLED = True
        UPLOAD_FOLDER = Path(tmp_path) / "uploads"
        REPORT_FOLDER = Path(tmp_path) / "reports"
        BACKUP_FOLDER = Path(tmp_path) / "backups"
        LOG_FOLDER = Path(tmp_path) / "logs"
        TEMP_FOLDER = Path(tmp_path) / "temp"
    return create_app(Config)


def _raw(upload_id, rep_id, name):
    from app.models import IMSRawData
    return IMSRawData(
        upload_id=upload_id,
        year=2026,
        month=2,
        week_number=9,
        sheet_name="TTS HAFTALIK CIKISLARI",
        sheet_type="weekly_sales",
        source_row=1,
        representative_id=rep_id,
        representative=name,
        product="TEST",
        unit=1,
        tl=1,
        raw_json="{}",
    )


def test_sync_uses_latest_business_ims_roster_and_only_changes_active_flag(tmp_path):
    app = _app(tmp_path)
    from app.extensions import db
    from app.models import IMSUpload, Product, Representative, Target
    from app.services.import_roster_sync import IMSRosterSyncService

    with app.app_context():
        db.create_all()
        product = Product(product_code="RSTR", product_name="Roster Product", is_active=True)
        a = Representative(rep_code="A", rep_name="A Rep", active=False)
        b = Representative(rep_code="B", rep_name="B Rep", active=True)
        c = Representative(rep_code="C", rep_name="C Rep", active=True)
        db.session.add_all([product, a, b, c]); db.session.flush()

        # An older period replay is imported later in wall-clock time. It must
        # not take authority away from the newest business period/week.
        old = IMSUpload(
            file_name="5.Hafta_Ocak.xlsx", year=2026, month=1, week_number=5,
            status="COMPLETED", completed_at=datetime(2026, 8, 30, 12, 0),
        )
        latest = IMSUpload(
            file_name="9.Hafta_Subat.xlsx", year=2026, month=2, week_number=9,
            status="COMPLETED", completed_at=datetime(2026, 8, 29, 12, 0),
        )
        db.session.add_all([old, latest]); db.session.flush()
        db.session.add(_raw(old.id, b.id, b.rep_name))
        db.session.add_all([_raw(latest.id, a.id, a.rep_name), _raw(latest.id, c.id, c.rep_name)])
        target = Target(
            year=2026, month=2, representative_id=b.id, product_id=product.id,
            unit_target=10, tl_target=1000,
        )
        db.session.add(target)
        db.session.commit()

        result = IMSRosterSyncService.sync_latest()

        assert result["upload_id"] == latest.id
        assert result["active_roster"] == 2
        assert result["activated"] == 1
        assert result["deactivated"] == 1
        assert db.session.get(Representative, a.id).active is True
        assert db.session.get(Representative, b.id).active is False
        assert db.session.get(Representative, c.id).active is True
        # Historical/business data remains intact; only Representative.active changes.
        assert db.session.get(Target, target.id) is not None
        assert db.session.get(Target, target.id).tl_target == 1000


def test_sync_refuses_empty_latest_roster_without_deactivating_everyone(tmp_path):
    app = _app(tmp_path)
    from app.extensions import db
    from app.models import IMSUpload, Representative
    from app.services.import_roster_sync import IMSRosterSyncService

    with app.app_context():
        db.create_all()
        rep = Representative(rep_code="SAFE", rep_name="Safe Rep", active=True)
        db.session.add(rep)
        db.session.add(IMSUpload(
            file_name="empty.xlsx", year=2026, month=2, week_number=9,
            status="COMPLETED", completed_at=datetime(2026, 8, 30, 12, 0),
        ))
        db.session.commit()

        with pytest.raises(RuntimeError, match="no resolved representatives"):
            IMSRosterSyncService.sync_latest()

        db.session.expire_all()
        assert db.session.get(Representative, rep.id).active is True


def test_vacancy_slot_reactivates_after_occupant_leaves_and_deactivates_for_replacement(tmp_path):
    app = _app(tmp_path)
    from app.extensions import db
    from app.models import IMSUpload, Representative
    from app.services.import_roster_sync import IMSRosterSyncService
    from app.services.ims_import_service import IMSImportService

    with app.app_context():
        db.create_all()
        vacancy_name = "DIYARBAKIR BOS KADRO"
        vacancy_code = IMSImportService._vacancy_code("901", vacancy_name)
        vacancy = Representative(
            rep_code=vacancy_code,
            rep_name="901 DIYARBAKIR BOS KADRO",
            region="901",
            city="DIYARBAKIR",
            territory="DIYARBAKIR",
            team="TAYFUN-1",
            active=False,
        )
        occupant = Representative(
            rep_code="OZGECAN-GULACAR",
            rep_name="OZGECAN GULACAR",
            region="901",
            city="DIYARBAKIR",
            territory="DIYARBAKIR",
            team="TAYFUN-1",
            active=True,
        )
        replacement = Representative(
            rep_code="NEW-DIYARBAKIR",
            rep_name="YENI DIYARBAKIR TEMSILCISI",
            region="901",
            city="DIYARBAKIR",
            territory="DIYARBAKIR",
            team="TAYFUN-1",
            active=False,
        )
        db.session.add_all([vacancy, occupant, replacement])
        db.session.flush()

        importer = IMSImportService("unused.xlsx")
        reused_id = importer._ensure_vacancy_representative(
            "901 DIYARBAKIR",
            vacancy_name=vacancy_name,
        )
        assert reused_id == vacancy.id
        assert db.session.get(Representative, vacancy.id).active is False

        vacancy_week = IMSUpload(
            file_name="10.Hafta_Subat.xlsx",
            year=2026,
            month=2,
            week_number=10,
            status="COMPLETED",
            completed_at=datetime(2026, 8, 30, 13, 0),
        )
        db.session.add(vacancy_week)
        db.session.flush()
        db.session.add(_raw(vacancy_week.id, vacancy.id, vacancy_name))
        db.session.commit()

        result = IMSRosterSyncService.sync_latest()
        assert result["upload_id"] == vacancy_week.id
        assert db.session.get(Representative, vacancy.id).active is True
        assert db.session.get(Representative, occupant.id).active is False

        replacement_week = IMSUpload(
            file_name="11.Hafta_Subat.xlsx",
            year=2026,
            month=2,
            week_number=11,
            status="COMPLETED",
            completed_at=datetime(2026, 8, 30, 14, 0),
        )
        db.session.add(replacement_week)
        db.session.flush()
        db.session.add(_raw(replacement_week.id, replacement.id, replacement.rep_name))
        db.session.commit()

        result = IMSRosterSyncService.sync_latest()
        assert result["upload_id"] == replacement_week.id
        assert db.session.get(Representative, vacancy.id).active is False
        assert db.session.get(Representative, occupant.id).active is False
        assert db.session.get(Representative, replacement.id).active is True
