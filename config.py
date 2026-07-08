from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Config:

    SECRET_KEY = "CHANGE_THIS_SECRET_KEY"

    SQLALCHEMY_DATABASE_URI = (
        "sqlite:///" +
        str(BASE_DIR / "instance" / "ipm.db")
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER = BASE_DIR / "uploads"

    REPORT_FOLDER = BASE_DIR / "reports"

    BACKUP_FOLDER = BASE_DIR / "backups"

    LOG_FOLDER = BASE_DIR / "logs"

    MAX_CONTENT_LENGTH = 100 * 1024 * 1024
