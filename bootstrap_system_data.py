#!/usr/bin/env python
"""Apply migrations and seed deterministic system defaults."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from flask_migrate import upgrade

from app import create_app
from app.database import initialize_database
from app.extensions import db
from app.models import (
    IMSFact,
    IMSRawData,
    IMSSummary,
    IMSUpload,
    PrimeRule,
    Product,
    Representative,
    Setting,
    User,
)
from config import Config


REPO_ROOT = Path(__file__).resolve().parent
MIGRATIONS_DIR = str(REPO_ROOT / "migrations")
DEFAULT_DB_URL = f"sqlite:///{(REPO_ROOT / 'instance' / 'ipm.db').resolve()}"


class BootstrapConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", DEFAULT_DB_URL)


def bootstrap() -> dict:
    app = create_app(BootstrapConfig)
    with app.app_context():
        upgrade(directory=MIGRATIONS_DIR)
        initialize_database()

        summary = {
            "database_url": app.config["SQLALCHEMY_DATABASE_URI"],
            "seed_counts": {
                "users": db.session.query(User).count(),
                "settings": db.session.query(Setting).count(),
                "products": db.session.query(Product).count(),
                "prime_rules": db.session.query(PrimeRule).count(),
            },
            "business_counts": {
                "representatives": db.session.query(Representative).count(),
                "ims_uploads": db.session.query(IMSUpload).count(),
                "ims_raw_data": db.session.query(IMSRawData).count(),
                "ims_facts": db.session.query(IMSFact).count(),
                "ims_summary": db.session.query(IMSSummary).count(),
            },
        }
    return summary


def main() -> int:
    try:
        summary = bootstrap()
    except Exception as exc:  # pragma: no cover - CLI safety
        print(f"[bootstrap] FAILED: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
