"""Role-aware access rules shared by routes and templates."""

from flask import flash, redirect, request, url_for
from flask_login import current_user


MANAGER_ROLES = {"admin", "administrator", "manager", "yönetici", "yonetici"}
MANAGER_ONLY_ENDPOINT_PREFIXES = ("ims.", "settings.")


def is_manager(user):
    return bool(
        getattr(user, "is_authenticated", False)
        and str(getattr(user, "role", "") or "").strip().casefold() in MANAGER_ROLES
    )


def register_access_control(app):
    @app.context_processor
    def role_context():
        return {"manager_access": is_manager(current_user)}

    @app.before_request
    def protect_manager_areas():
        if not current_user.is_authenticated:
            return None
        endpoint = request.endpoint or ""
        if endpoint.startswith(MANAGER_ONLY_ENDPOINT_PREFIXES) and not is_manager(current_user):
            flash("Bu alan yalnızca yönetici hesaplarına açıktır.", "warning")
            return redirect(url_for("dashboard.index"))
        return None
