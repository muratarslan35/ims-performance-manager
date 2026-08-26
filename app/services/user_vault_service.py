"""Durable user storage kept independently from the IMS database."""

import sqlite3
import os
from contextlib import closing
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
        connection = sqlite3.connect(cls._path(), timeout=30)
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
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
                saved_at TEXT NOT NULL,
                user_id INTEGER
            )
            """
        )
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        if "user_id" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN user_id INTEGER")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_user_vault_user_id "
            "ON users(user_id) WHERE user_id IS NOT NULL"
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
        with closing(cls._connect()) as connection:
            with connection:
                for user in users:
                    connection.execute(
                        """
                        INSERT INTO users
                        (email, full_name, password, phone, role, active,
                         last_login, created_at, saved_at, user_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(email) DO UPDATE SET
                            full_name=excluded.full_name,
                            password=excluded.password,
                            phone=excluded.phone,
                            role=excluded.role,
                            active=excluded.active,
                            last_login=excluded.last_login,
                            created_at=excluded.created_at,
                            saved_at=excluded.saved_at,
                            user_id=excluded.user_id
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
                            user.id,
                        ),
                    )

    @classmethod
    def load_user_by_id(cls, user_id):
        """Load a detached Flask-Login user from the independent vault.

        This is intentionally read-only and used only when the primary IMS
        database has a transient SQLite lock.  It prevents a long IMS write
        transaction from taking authenticated pages down with a 500 response.
        """
        if not cls._enabled():
            return None
        try:
            numeric_id = int(user_id)
        except (TypeError, ValueError):
            return None

        path = cls._path()
        if not path.exists():
            return None
        with closing(cls._connect()) as connection:
            row = connection.execute(
                """
                SELECT user_id, email, full_name, password, phone, role, active,
                       last_login, created_at
                FROM users
                WHERE user_id = ?
                """,
                (numeric_id,),
            ).fetchone()
        if row is None:
            return None

        return User(
            id=row[0],
            email=row[1],
            full_name=row[2],
            password=row[3],
            phone=row[4],
            role=row[5],
            active=bool(row[6]),
            last_login=datetime.fromisoformat(row[7]) if row[7] else None,
            created_at=datetime.fromisoformat(row[8]),
        )

    @classmethod
    def restore_to_primary(cls):
        if not cls._enabled():
            return 0
        path = cls._path()
        if not path.exists():
            return 0
        with closing(cls._connect()) as connection:
            rows = connection.execute(
                """
                SELECT user_id, email, full_name, password, phone, role, active,
                       last_login, created_at
                FROM users
                """
            ).fetchall()

        restored = 0
        for row in rows:
            if User.query.filter(db.func.lower(User.email) == row[1].lower()).first():
                continue
            kwargs = {
                "email": row[1],
                "full_name": row[2],
                "password": row[3],
                "phone": row[4],
                "role": row[5],
                "active": bool(row[6]),
                "last_login": datetime.fromisoformat(row[7]) if row[7] else None,
                "created_at": datetime.fromisoformat(row[8]),
            }
            if row[0] is not None and db.session.get(User, row[0]) is None:
                kwargs["id"] = row[0]
            db.session.add(User(**kwargs))
            restored += 1
        if restored:
            db.session.commit()
        return restored

    @classmethod
    def reconcile(cls):
        cls.restore_to_primary()
        cls.sync_from_primary()
