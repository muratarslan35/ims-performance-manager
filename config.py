import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:

    SECRET_KEY = os.environ.get(
        "SECRET_KEY",
        "ipm-secret-key"
    )

    SQLALCHEMY_DATABASE_URI = \
        "sqlite:///" + os.path.join(
            BASE_DIR,
            "instance",
            "ipm.db"
        )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER = os.path.join(
        BASE_DIR,
        "uploads"
    )

    REPORT_FOLDER = os.path.join(
        BASE_DIR,
        "reports"
    )
