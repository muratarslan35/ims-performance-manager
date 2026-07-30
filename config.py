import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

_SECRET_KEY_ENV = os.environ.get("SECRET_KEY")

if not _SECRET_KEY_ENV:
    import warnings
    warnings.warn(
        "SECRET_KEY environment variable is not set. "
        "A temporary key is used – set SECRET_KEY in production!",
        stacklevel=2,
    )


class Config:

    # ------------------------------------------------------------------
    # Uygulama
    # ------------------------------------------------------------------

    SECRET_KEY = _SECRET_KEY_ENV or "dev-only-insecure-key-change-in-production"

    RESET_TOKEN_MAX_AGE = 60 * 60

    DEBUG = False

    TESTING = False

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------

    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///" + str(BASE_DIR / "instance" / "ipm.db"),
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

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
