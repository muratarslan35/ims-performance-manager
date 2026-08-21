"""Role-aware access rules shared by routes and templates."""

import hashlib

from flask import flash, redirect, request, session, url_for
from flask_login import current_user


MANAGER_ROLES = {"admin", "administrator", "manager", "yönetici", "yonetici"}
MANAGER_ONLY_ENDPOINT_PREFIXES = ("ims.", "settings.")
DUAL_PORTAL_EMAIL_HASHES = {
    "192ef0622a370d063bbada9e29ff3137d7580691186bed0ab0a44c3d631278c0",
}


def is_manager(user):
    return bool(
        getattr(user, "is_authenticated", False)
        and str(getattr(user, "role", "") or "").strip().casefold() in MANAGER_ROLES
    )


def has_dual_portal_access(user):
    """Allow explicitly authorised managers to open the limited field portal."""
    email = str(getattr(user, "email", "") or "").strip().casefold()
    return bool(
        is_manager(user)
        and hashlib.sha256(email.encode("utf-8")).hexdigest()
        in DUAL_PORTAL_EMAIL_HASHES
    )


def has_manager_access(user):
    """Return the effective access level for the portal selected at login."""
    if not is_manager(user):
        return False
    return not (
        session.get("portal") == "representative"
        and has_dual_portal_access(user)
    )


def register_access_control(app):
    @app.context_processor
    def role_context():
        return {
            "manager_access": has_manager_access(current_user),
            "dual_portal_access": has_dual_portal_access(current_user),
            "portal_mode": session.get("portal"),
        }

    @app.before_request
    def protect_manager_areas():
        if not current_user.is_authenticated:
            return None
        endpoint = request.endpoint or ""
        if endpoint.startswith(MANAGER_ONLY_ENDPOINT_PREFIXES) and not has_manager_access(current_user):
            flash("Bu alan yalnızca yönetici hesaplarına açıktır.", "warning")
            return redirect(url_for("dashboard.index"))
        return None
