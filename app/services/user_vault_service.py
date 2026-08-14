"""Durable user storage kept independently from the IMS database."""

import sqlite3
import os
from datetime import datetime
from pathlib import Path

from flask import current_app

from app.extensions import db
from app.models import User


class UserVaultService:
    @staticmethod
    def _path():
        path = Path(current_app.config["USER_VAULT_PATH"])
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        return path

    @classmethod
    def _connect(cls):
        connection = sqlite3.connect(cls._path())
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY COLLATE NOCASE,
                full_name TEXT NOT NULL,
                password TEXT NOT NULL,
                phone TEXT,
                role TEXT NOT NULL,
                active INTEGER NOT NULL,
                last_login TEXT,
                created_at TEXT NOT NULL,
                saved_at TEXT NOT NULL
            )
            """
        )
        os.chmod(cls._path(), 0o600)
        return connection

    @staticmethod
    def _enabled():
        return not current_app.config.get("TESTING", False) or current_app.config.get(
            "TEST_USER_VAULT_ENABLED", False
        )

    @classmethod
    def sync_from_primary(cls):
        if not cls._enabled():
            return
        users = User.query.all()
        now = datetime.utcnow().isoformat()
        with cls._connect() as connection:
            for user in users:
                connection.execute(
                    """
                    INSERT INTO users
                    (email, full_name, password, phone, role, active,
                     last_login, created_at, saved_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(email) DO UPDATE SET
                        full_name=excluded.full_name,
                        password=excluded.password,
                        phone=excluded.phone,
                        role=excluded.role,
                        active=excluded.active,
                        last_login=excluded.last_login,
                        created_at=excluded.created_at,
                        saved_at=excluded.saved_at
                    """,
                    (
                        user.email,
                        user.full_name,
                        user.password,
                        user.phone,
                        user.role,
                        int(user.active),
                        user.last_login.isoformat() if user.last_login else None,
                        user.created_at.isoformat(),
                        now,
                    ),
                )

    @classmethod
    def restore_to_primary(cls):
        if not cls._enabled():
            return 0
        path = cls._path()
        if not path.exists():
            return 0
        with cls._connect() as connection:
            rows = connection.execute(
                """
                SELECT email, full_name, password, phone, role, active,
                       last_login, created_at
                FROM users
                """
            ).fetchall()

        restored = 0
        for row in rows:
            if User.query.filter(db.func.lower(User.email) == row[0].lower()).first():
                continue
            db.session.add(
                User(
                    email=row[0],
                    full_name=row[1],
                    password=row[2],
                    phone=row[3],
                    role=row[4],
                    active=bool(row[5]),
                    last_login=datetime.fromisoformat(row[6]) if row[6] else None,
                    created_at=datetime.fromisoformat(row[7]),
                )
            )
            restored += 1
        if restored:
            db.session.commit()
        return restored

    @classmethod
    def reconcile(cls):
        cls.restore_to_primary()
        cls.sync_from_primary()
