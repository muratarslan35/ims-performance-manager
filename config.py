import os
import secrets
import warnings
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _development_secret_key():
    """Return a persistent local development key without committing a secret."""
    key_path = BASE_DIR / "instance" / ".secret_key"
    try:
        if key_path.exists():
            value = key_path.read_text(encoding="utf-8").strip()
            if value:
                return value
        key_path.parent.mkdir(parents=True, exist_ok=True)
        value = secrets.token_urlsafe(48)
        fd = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value + "\n")
        return value
    except FileExistsError:
        return key_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        warnings.warn("Kalıcı geliştirme SECRET_KEY oluşturulamadı: %s" % exc, stacklevel=2)
        return secrets.token_urlsafe(48)

_SECRET_KEY_ENV = os.environ.get("SECRET_KEY")
_APP_ENV = os.environ.get("APP_ENV", os.environ.get("FLASK_ENV", "development")).lower()
_IS_PRODUCTION = _APP_ENV == "production"

if _IS_PRODUCTION and not _SECRET_KEY_ENV:
    raise RuntimeError(
        "SECRET_KEY environment variable must be set when APP_ENV is production."
    )

_SECRET_KEY = _SECRET_KEY_ENV or (_development_secret_key() if not _IS_PRODUCTION else None)
_DATABASE_URI = os.getenv(
    "DATABASE_URL",
    "sqlite:///" + str(BASE_DIR / "instance" / "ipm.db"),
)
_SQLITE_ENGINE_OPTIONS = {
    "pool_pre_ping": True,
    "connect_args": {
        "timeout": 30,
        "check_same_thread": False,
    },
}
_DEFAULT_ENGINE_OPTIONS = {"pool_pre_ping": True}


class Config:

    # ------------------------------------------------------------------
    # Uygulama
    # ------------------------------------------------------------------

    SECRET_KEY = _SECRET_KEY
    APP_ENV = _APP_ENV
    STRICT_SCHEMA_VALIDATION = _IS_PRODUCTION

    RESET_TOKEN_MAX_AGE = 60 * 60

    DEBUG = False

    TESTING = False

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------

    SQLALCHEMY_DATABASE_URI = _DATABASE_URI

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # SQLite is the current single-server production store.  A bounded DB-API
    # timeout complements the WAL/busy_timeout pragmas installed at runtime.
    SQLALCHEMY_ENGINE_OPTIONS = (
        _SQLITE_ENGINE_OPTIONS if _DATABASE_URI.startswith("sqlite:") else _DEFAULT_ENGINE_OPTIONS
    )

    USER_VAULT_PATH = Path(
        os.getenv("USER_VAULT_PATH", str(BASE_DIR / "instance" / "persistent" / "users.db"))
    )

    # ------------------------------------------------------------------
    # Dosya Klasörleri
    # ------------------------------------------------------------------

    UPLOAD_FOLDER = BASE_DIR / "uploads"

    REPORT_FOLDER = BASE_DIR / "reports"

    BACKUP_FOLDER = BASE_DIR / "backups"

    LOG_FOLDER = BASE_DIR / "logs"

    TEMP_FOLDER = BASE_DIR / "temp"

    # ------------------------------------------------------------------
    # Dosya Limitleri
    # ------------------------------------------------------------------

    MAX_CONTENT_LENGTH = 100 * 1024 * 1024

    ALLOWED_EXTENSIONS = {

        "xlsx",

        "xls"

    }

    # ------------------------------------------------------------------
    # IMS
    # ------------------------------------------------------------------

    DEFAULT_YEAR = 2026

    DEFAULT_MONTH = 1

    DEFAULT_QUARTER = "Q1"

    IMS_IMPORT_LOCK_WAIT_SECONDS = float(os.getenv("IMS_IMPORT_LOCK_WAIT_SECONDS", "2"))

    # ------------------------------------------------------------------
    # Prim Sistemi
    # ------------------------------------------------------------------

    MAIN_PRIME = 50000

    CIRO_PRIME = 20000

    PRIME_STEP = 5

    STEP_AMOUNT = 2500

    MAX_PRIME_PERCENT = 140

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    DASHBOARD_PAGE_SIZE = 20

    DEFAULT_CURRENCY = "₺"

    DATE_FORMAT = "%d.%m.%Y"

    DATETIME_FORMAT = "%d.%m.%Y %H:%M"

    # ------------------------------------------------------------------
    # Excel
    # ------------------------------------------------------------------

    EXCEL_ENGINE = "openpyxl"
