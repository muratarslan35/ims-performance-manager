"""Keep representative detail selector inside a regional manager's allowed scope.

The legacy representative detail template limits its selector to one item when
portal mode is ``representative``.  For a region-scoped manager we temporarily
use that rendering mode for the allowed detail request, then restore the manager
portal before the response is saved.  Access checks are performed separately by
``region_manager`` and remain authoritative.
"""

from flask import g, request, session
from flask_login import current_user

from app.region_manager import is_regional_manager


def install_region_manager_detail_scope(app):
    @app.before_request
    def narrow_representative_detail_selector():
        if (
            current_user.is_authenticated
            and is_regional_manager(current_user)
            and request.endpoint == "representatives.view"
        ):
            g._regional_manager_portal = session.get("portal")
            session["portal"] = "representative"
        return None

    @app.after_request
    def restore_manager_portal(response):
        if hasattr(g, "_regional_manager_portal"):
            original = g._regional_manager_portal
            if original is None:
                session.pop("portal", None)
            else:
                session["portal"] = original
        return response
