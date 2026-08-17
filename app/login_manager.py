import time

from flask import current_app
from sqlalchemy.exc import OperationalError

from app.extensions import db, login_manager
from app.models import User


def _is_sqlite_locked(exc) -> bool:
    return "database is locked" in str(exc).lower() or "database table is locked" in str(exc).lower()


@login_manager.user_loader
def load_user(user_id):
    try:
        numeric_id = int(user_id)
    except (TypeError, ValueError):
        return None

    # WAL mode should make reads non-blocking during the long atomic IMS write.
    # Keep a very small retry as defense in depth for schema/checkpoint windows.
    for attempt in range(3):
        try:
            return db.session.get(User, numeric_id)
        except OperationalError as exc:
            db.session.rollback()
            if not _is_sqlite_locked(exc):
                raise
            current_app.logger.warning(
                "auth_primary_db_locked user_id=%s attempt=%s",
                numeric_id,
                attempt + 1,
            )
            if attempt < 2:
                time.sleep(0.05 * (attempt + 1))

    # The durable user vault lives in a separate SQLite file.  If the primary
    # IMS database still has a transient lock, use the read-only vault copy so
    # an authenticated manager does not receive a 500 error or get logged out.
    try:
        from app.services.user_vault_service import UserVaultService

        user = UserVaultService.load_user_by_id(numeric_id)
        if user is not None:
            current_app.logger.warning("auth_user_loaded_from_vault user_id=%s", numeric_id)
        return user
    except Exception:
        current_app.logger.exception("auth_vault_fallback_failed user_id=%s", numeric_id)
        return None


def init_app(app):
    login_manager.init_app(app)
