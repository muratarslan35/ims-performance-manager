import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
MIGRATIONS_DIR = str(Path(__file__).resolve().parents[1] / "migrations")


@pytest.fixture()
def resilient_app():
    os.environ.setdefault("APP_ENV", "development")
    os.environ.setdefault("SECRET_KEY", "test-secret-key")

    from app import create_app

    temp_dir = tempfile.TemporaryDirectory()
    root = Path(temp_dir.name)
    db_path = root / "resilience.db"

    class TestConfig:
        TESTING = True
        SECRET_KEY = "test-secret-key"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        LOGIN_DISABLED = False
        TEST_USER_VAULT_ENABLED = True
        USER_VAULT_PATH = root / "users.db"
        UPLOAD_FOLDER = root / "uploads"
        REPORT_FOLDER = root / "reports"
        BACKUP_FOLDER = root / "backups"
        LOG_FOLDER = root / "logs"
        TEMP_FOLDER = root / "temp"
        IMS_IMPORT_LOCK_WAIT_SECONDS = 0

    application = create_app(TestConfig)

    with application.app_context():
        from flask_migrate import upgrade
        from app.database import initialize_database
        from app.extensions import db

        upgrade(directory=MIGRATIONS_DIR)
        initialize_database()
        db.session.remove()

    application.config["TEST_DB_PATH"] = db_path
    yield application

    with application.app_context():
        from app.extensions import db
        db.session.remove()
        db.engine.dispose()
    temp_dir.cleanup()


def test_sqlite_runtime_enables_wal_and_busy_timeout(resilient_app):
    from app.extensions import db

    with resilient_app.app_context():
        with db.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"
            assert int(connection.exec_driver_sql("PRAGMA busy_timeout").scalar()) >= 30000


def test_authenticated_read_survives_concurrent_ims_writer(resilient_app):
    from app.extensions import db
    from app.models import User
    from werkzeug.security import generate_password_hash

    with resilient_app.app_context():
        user = User(
            full_name="Concurrent Reader",
            email="reader@example.com",
            password=generate_password_hash("password123"),
            role="Admin",
            active=True,
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id
        db.session.remove()

    writer = sqlite3.connect(resilient_app.config["TEST_DB_PATH"], timeout=1)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE users SET full_name = ? WHERE id = ?", ("Uncommitted Writer", user_id))

        with resilient_app.app_context():
            from app.extensions import db
            from app.models import User

            loaded = db.session.get(User, user_id)
            assert loaded is not None
            assert loaded.full_name == "Concurrent Reader"
            db.session.remove()
    finally:
        writer.rollback()
        writer.close()


def test_user_vault_can_load_session_identity_independently(resilient_app):
    from app.extensions import db
    from app.models import User
    from app.services.user_vault_service import UserVaultService
    from werkzeug.security import generate_password_hash

    with resilient_app.app_context():
        user = User(
            full_name="Vault Manager",
            email="vault@example.com",
            password=generate_password_hash("password123"),
            role="Admin",
            active=True,
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id
        UserVaultService.sync_from_primary()
        db.session.remove()

        detached = UserVaultService.load_user_by_id(user_id)
        assert detached is not None
        assert detached.id == user_id
        assert detached.full_name == "Vault Manager"
        assert detached.is_authenticated


def test_import_coordinator_rejects_second_writer_with_metadata(resilient_app):
    from app.services.import_coordinator import ImportBusyError, ImportCoordinator

    with resilient_app.app_context():
        with ImportCoordinator.acquire(uploaded_by="Yönetici A", file_name="week4-a.xlsx", wait_seconds=0):
            with pytest.raises(ImportBusyError) as exc_info:
                with ImportCoordinator.acquire(uploaded_by="Yönetici B", file_name="week4-b.xlsx", wait_seconds=0):
                    pass

        assert exc_info.value.metadata["uploaded_by"] == "Yönetici A"
        assert exc_info.value.metadata["file_name"] == "week4-a.xlsx"


def test_vacancy_matching_resolves_diyarbakir_rows_without_guessing(resilient_app):
    from app.extensions import db
    from app.models import Representative
    from app.services.alias_service import AliasService
    from app.services.vacancy_matching import clear_vacancy_match_cache

    with resilient_app.app_context():
        vacancy = Representative(
            rep_code="UNASSIGNED901DIYARBAKIRBOS",
            rep_name="ATANMAMIŞ · 901 DIYARBAKIR · DIYARBAKIR BOS",
            region="901 DIYARBAKIR",
            city="DIYARBAKIR",
            active=False,
        )
        vacancy_cadre = Representative(
            rep_code="UNASSIGNED901DIYARBAKIRBOSKADRO",
            rep_name="ATANMAMIŞ · 901 DIYARBAKIR · DIYARBAKIR BOS KADRO",
            region="901 DIYARBAKIR",
            city="DIYARBAKIR",
            active=False,
        )
        db.session.add_all([vacancy, vacancy_cadre])
        db.session.commit()
        AliasService.clear_cache()
        clear_vacancy_match_cache()

        plain = AliasService.find_representative("DIYARBAKIR BOS")
        cadre = AliasService.find_representative("DIYARBAKIR BOS KADRO")

        assert plain["matched"] is True
        assert plain["object"].id == vacancy.id
        assert plain["method"] == "VACANCY_SUFFIX"
        assert cadre["matched"] is True
        assert cadre["object"].id == vacancy_cadre.id
        assert cadre["method"] == "VACANCY_SUFFIX"

        ordinary = AliasService.find_representative("BOSTANCI TEMSILCI")
        assert ordinary["matched"] is False


def test_unresolved_vacancy_is_rechecked_after_bootstrap_creates_stable_slot(resilient_app):
    """A pre-bootstrap miss must not poison later master parsers in the same import."""
    from app.extensions import db
    from app.models import Representative
    from app.services.alias_service import AliasService
    from app.services.vacancy_matching import clear_vacancy_match_cache

    with resilient_app.app_context():
        clear_vacancy_match_cache()
        AliasService.clear_cache()

        before = AliasService.find_representative("ISTANBUL BOS")
        assert before["matched"] is False
        assert before["method"] == "VACANCY_UNRESOLVED"

        vacancy = Representative(
            rep_code="UNASSIGNED101BOSISTANBULBOS",
            rep_name="ATANMAMIŞ · 101 ISTANBUL · ISTANBUL BOS",
            region="101 ISTANBUL",
            city="ISTANBUL",
            active=False,
        )
        db.session.add(vacancy)
        db.session.flush()

        after = AliasService.find_representative("ISTANBUL BOS")
        assert after["matched"] is True
        assert after["object"].id == vacancy.id
        assert after["method"] == "VACANCY_SUFFIX"


def test_bootstrap_reuses_legacy_vacancy_primary_key_instead_of_creating_duplicate(resilient_app):
    """Canonical code changes must never fork a historic vacancy/cadre identity."""
    from app.extensions import db
    from app.models import Representative
    from app.services.ims_import_service import IMSImportService
    from app.services.vacancy_matching import clear_vacancy_match_cache

    with resilient_app.app_context():
        legacy = Representative(
            rep_code="UNASSIGNED101ISTANBULBOS",
            rep_name="ATANMAMIŞ · 101 ISTANBUL · ISTANBUL BOS",
            region="101 ISTANBUL",
            city="ISTANBUL",
            active=False,
        )
        db.session.add(legacy)
        db.session.flush()
        legacy_id = legacy.id
        clear_vacancy_match_cache()

        service = IMSImportService("unused.xlsx")
        resolved = service._ensure_vacancy_representative(
            "ISTANBUL BOS",
            region_value="101 ISTANBUL",
            city="ISTANBUL",
        )
        db.session.flush()

        assert resolved.id == legacy_id
        assert Representative.query.filter(Representative.rep_name.like("%ISTANBUL BOS%")).count() == 1
        assert resolved.rep_code == "UNASSIGNED101ISTANBULBOS"


def test_online_backup_is_consistent_in_wal_mode(resilient_app):
    from sqlite_online_backup import backup

    source = Path(resilient_app.config["TEST_DB_PATH"])
    destination = source.parent / "backup.db"
    result = backup(source, destination)

    assert destination.is_file()
    assert result["integrity_check"] == "ok"
    with sqlite3.connect(destination) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0].lower() == "ok"
