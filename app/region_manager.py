"""Unified manager administration and access enforcement.

Regional managers are restricted to their assigned region. Functional managers
(Tanitim/Urun/Pazarlama) keep full operational access but cannot open Settings.
Admin and preserved special managers keep their existing unrestricted access.
"""

from datetime import datetime
import hashlib
import re
from functools import wraps
from urllib.parse import unquote

from flask import Blueprint, flash, has_request_context, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from werkzeug.security import generate_password_hash

from app.access_control import has_dual_portal_access, has_manager_access, is_manager
from app.extensions import db
from app.models import Product, Representative, RepresentativeBrickAssignment, User
from app.services.access_permission_service import enabled as access_enabled


UNRESTRICTED_REGION_MANAGER_EMAIL_HASHES = {
    # Existing murat.asan@bilimilac.com manager keeps its previously defined access.
    "c14c76f05798cf3933ef16395d8f5afaf2179d37165c9801208de2d7c38a52ec",
}

MANAGER_TYPES = {
    "region": "Bölge Müdürü",
    "promotion": "Tanıtım Müdürü",
    "product": "Ürün Müdürü",
    "marketing": "Pazarlama Müdürü",
}
MANAGER_MUTATION_TYPES = {"promotion", "marketing"}


class RegionManagerScope(db.Model):
    __tablename__ = "region_manager_scopes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False, index=True)
    region_code = db.Column(db.String(20), nullable=True, index=True)
    manager_type = db.Column(db.String(20), nullable=False, default="region", server_default="region", index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = db.relationship("User", backref=db.backref("region_manager_scope", uselist=False))


def region_code(value):
    match = re.search(r"(?<!\d)(\d{3})(?!\d)", str(value or ""))
    return match.group(1) if match else ""


def _email_hash(user):
    email = str(getattr(user, "email", "") or "").strip().casefold()
    return hashlib.sha256(email.encode("utf-8")).hexdigest() if email else ""


def is_privileged_manager(user):
    role = str(getattr(user, "role", "") or "").strip().casefold()
    return bool(
        getattr(user, "is_authenticated", False)
        and (
            role in {"admin", "administrator"}
            or has_dual_portal_access(user)
            or _email_hash(user) in UNRESTRICTED_REGION_MANAGER_EMAIL_HASHES
        )
    )


def _scope_for(user):
    user_id = getattr(user, "id", None)
    if not user_id:
        return None
    try:
        return RegionManagerScope.query.filter_by(user_id=user_id).one_or_none()
    except Exception:
        return None


def manager_type(user):
    if not is_manager(user):
        return None
    if is_privileged_manager(user):
        return "privileged"
    scope = _scope_for(user)
    value = str(getattr(scope, "manager_type", "") or "region").strip().casefold()
    return value if value in MANAGER_TYPES else "region"


def manager_type_label(user):
    kind = manager_type(user)
    if kind == "privileged":
        role = str(getattr(user, "role", "") or "").strip().casefold()
        return "Admin" if role in {"admin", "administrator"} else "Yönetici"
    return MANAGER_TYPES.get(kind, "Yönetici")


def is_regional_manager(user):
    return bool(is_manager(user) and not is_privileged_manager(user) and manager_type(user) == "region")


def is_functional_manager(user):
    return bool(manager_type(user) in {"promotion", "product", "marketing"})


def is_field_portal():
    return bool(
        has_request_context()
        and getattr(current_user, "is_authenticated", False)
        and session.get("portal") == "representative"
        and session.get("portal_explicit", False)
    )


def _region_identity(value):
    code = region_code(value)
    return code or str(value or "").strip().casefold()


def current_field_representative():
    """Resolve the signed-in field user without a fuzzy cross-user match."""
    if not is_field_portal():
        return None
    email = str(getattr(current_user, "email", "") or "").strip().casefold()
    if email:
        exact = Representative.query.filter(db.func.lower(Representative.email) == email).all()
        if len(exact) == 1:
            return exact[0]
    from app.services.alias_service import AliasService
    name = AliasService.normalize(getattr(current_user, "full_name", ""))
    matches = [row for row in Representative.query.all() if AliasService.normalize(row.rep_name) == name]
    return matches[0] if len(matches) == 1 else None


def field_region():
    representative = current_field_representative()
    return _region_identity(representative.region) if representative else None


def can_view_manager_module(user):
    return bool(is_manager(user) and access_enabled(user, "manager_module"))


def can_manage_managers(user):
    if not getattr(user, "is_authenticated", False):
        return False
    return bool(
        is_manager(user)
        and access_enabled(user, "manager_module")
        and access_enabled(user, "manage_managers")
    )


def can_access_settings(user):
    role = str(getattr(user, "role", "") or "").strip().casefold()
    return bool(getattr(user, "is_authenticated", False) and role in {"admin", "administrator"})


def assigned_region(user):
    if not is_regional_manager(user):
        return None
    scope = _scope_for(user)
    return region_code(scope.region_code) if scope else None


def representative_in_region(representative, code):
    return bool(representative is not None and code and _region_identity(representative.region) == code)


def can_access_representative(user, representative):
    if access_enabled(user, "cross_region_details"):
        return True
    if is_field_portal() and getattr(user, "id", None) == getattr(current_user, "id", None):
        return representative_in_region(representative, field_region())
    if not is_regional_manager(user):
        return True
    return representative_in_region(representative, assigned_region(user))


def can_access_region(user, candidate):
    if access_enabled(user, "cross_region_details"):
        return True
    if is_field_portal() and getattr(user, "id", None) == getattr(current_user, "id", None):
        code = field_region()
        return bool(code and _region_identity(candidate) == code)
    if not is_regional_manager(user):
        return True
    return bool(assigned_region(user) and region_code(candidate) == assigned_region(user))


def available_regions():
    rows = Representative.query.order_by(Representative.region.asc(), Representative.city.asc()).all()
    choices = {}
    for representative in rows:
        code = region_code(representative.region)
        if not code:
            continue
        label_parts = [code]
        city = str(representative.city or "").strip()
        region_value = str(representative.region or "").strip()
        descriptive = city or re.sub(r"^\s*\d{3}\s*", "", region_value).strip()
        if descriptive and descriptive.casefold() != code.casefold():
            label_parts.append(descriptive)
        choices.setdefault(code, " - ".join(label_parts))
    return sorted(choices.items(), key=lambda item: int(item[0]))


def _deny_region(json_response=False):
    message = "Bu bölgenin yöneticisi değilsiniz."
    if json_response:
        return jsonify({"success": False, "message": message}), 403
    flash(message, "warning")
    return redirect(url_for("dashboard.index"))


def _deny_system(json_response=False):
    message = "Bölge müdürü hesabınızla bu alanda değişiklik yapamazsınız."
    if json_response:
        return jsonify({"success": False, "message": message}), 403
    flash(message, "warning")
    return redirect(url_for("dashboard.index"))


def _deny_field(json_response=False):
    message = "Temsilci hesabınızla bu alana erişemezsiniz."
    if json_response:
        return jsonify({"success": False, "message": message}), 403
    flash(message, "warning")
    return redirect(url_for("dashboard.index"))


def _deny_settings(json_response=False):
    message = "Bu yönetici hesabıyla Ayarlar menüsüne erişemezsiniz."
    if json_response:
        return jsonify({"success": False, "message": message}), 403
    flash(message, "warning")
    return redirect(url_for("dashboard.index"))


def _deny_permission(json_response=False):
    if is_field_portal():
        message = "Temsilci hesabınızla bu alana erişemezsiniz. Yetkiyi sistem yöneticiniz değiştirebilir."
    elif is_regional_manager(current_user):
        message = "Bölge müdürü hesabınızla bu alanda değişiklik yapamazsınız. Yetkiyi sistem yöneticiniz değiştirebilir."
    else:
        message = "Bu ekran için erişim yetkiniz aktif değildir. Yetkiyi sistem yöneticiniz değiştirebilir."
    if json_response:
        return jsonify({"success": False, "message": message}), 403
    flash(message, "warning")
    return redirect(url_for("dashboard.index"))


def _endpoint_permission(endpoint):
    exact = {
        "main.market_analysis": "market_analysis", "main.prime": "prime_center",
        "main.quarter": "q_analysis", "main.recovery": "recovery", "main.reports": "reports",
    }
    if endpoint in exact:
        return exact[endpoint]
    prefixes = (
        ("ims.", "ims_center"), ("representatives.territory_", "region_assignments"),
        ("products.", "products"), ("targets.", "targets"), ("matching.", "manual_matching"),
        ("simulation.", "prime_simulation"), ("manager_users.", "manager_module"),
    )
    return next((permission for prefix, permission in prefixes if endpoint.startswith(prefix)), None)


def _json_rep_id():
    data = request.get_json(silent=True) or {}
    try:
        return int(data.get("representative_id", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _request_rep_allowed(rep_id):
    representative = db.session.get(Representative, rep_id) if rep_id else None
    return can_access_representative(current_user, representative)


def _scoped_representatives(active_only=False):
    code = field_region() if is_field_portal() else assigned_region(current_user)
    query = Representative.query
    if active_only:
        query = query.filter(Representative.active.is_(True))
    rows = query.order_by(Representative.region.asc(), Representative.city.asc(), Representative.rep_name.asc()).all()
    return [row for row in rows if representative_in_region(row, code)]


def _restricted_representatives_index():
    latest = RepresentativeBrickAssignment.query.order_by(
        RepresentativeBrickAssignment.year.desc(), RepresentativeBrickAssignment.month.desc()
    ).first()
    assignments_by_rep = {}
    representatives = _scoped_representatives(active_only=False)
    rep_ids = {row.id for row in representatives}
    if latest and rep_ids:
        assignments = RepresentativeBrickAssignment.query.filter_by(
            year=latest.year, month=latest.month, active=True
        ).order_by(RepresentativeBrickAssignment.brick.asc()).all()
        for assignment in assignments:
            if assignment.representative_id in rep_ids:
                assignments_by_rep.setdefault(assignment.representative_id, []).append(assignment)
    return render_template(
        "representatives.html",
        representatives=representatives,
        assignments_by_rep=assignments_by_rep,
        assignment_period=(latest.year, latest.month) if latest else None,
    )


def _restricted_simulation_index():
    representatives = _scoped_representatives(active_only=True)
    representatives.sort(
        key=lambda representative: (
            str(representative.rep_name or "").strip().upper().startswith(("ATANMAMIŞ", "ATANMAMIS")),
            str(representative.rep_name or "").strip().upper(),
        )
    )
    products = Product.query.filter_by(is_active=True).order_by(Product.display_order.asc()).all()
    return render_template("simulation.html", representatives=representatives, products=products)


def _restricted_quarter():
    from app.services.quarter_entitlement_service import QuarterEntitlementService

    representatives = _scoped_representatives(active_only=True)
    year = request.args.get("year", type=int) or 2026
    quarter = request.args.get("quarter", type=int) or 2
    representative_id = request.args.get("representative_id", type=int)
    report = None
    selected_representative = None
    if representative_id:
        selected_representative = db.session.get(Representative, representative_id)
        if not can_access_representative(current_user, selected_representative):
            return _deny_region()
        if selected_representative is None:
            return _deny_region()
        report = QuarterEntitlementService(representative_id, year, quarter).report()
    return render_template(
        "quarter.html",
        representatives=representatives,
        selected_representative=selected_representative,
        report=report,
        selected_year=year,
        selected_quarter=quarter,
    )


def _filter_search_response(response):
    if not (is_regional_manager(current_user) or is_field_portal()) or not response.is_json:
        return response
    payload = response.get_json(silent=True) or {}
    results = payload.get("results")
    if not isinstance(results, list):
        return response
    allowed = []
    for item in results:
        target = str(item.get("url") or "")
        rep_match = re.search(r"/representatives/view/(\d+)", target)
        if rep_match:
            representative = db.session.get(Representative, int(rep_match.group(1)))
            if can_access_representative(current_user, representative):
                allowed.append(item)
            continue
        region_match = re.search(r"/regions/([^?]+)", target)
        if region_match:
            if can_access_region(current_user, unquote(region_match.group(1))):
                allowed.append(item)
            continue
    payload["results"] = allowed
    response.set_data(jsonify(payload).get_data())
    response.content_type = "application/json"
    return response


def install_region_manager_scope(app):
    """Install manager role restrictions after all blueprints."""
    original_rep_index = app.view_functions.get("representatives.index")
    original_sim_index = app.view_functions.get("simulation.index")
    original_quarter = app.view_functions.get("main.quarter")
    original_territory_index = app.view_functions.get("representatives.territory_management")

    if original_rep_index:
        @wraps(original_rep_index)
        def rep_index_wrapper(*args, **kwargs):
            if is_regional_manager(current_user) or is_field_portal():
                return _restricted_representatives_index()
            return original_rep_index(*args, **kwargs)
        app.view_functions["representatives.index"] = rep_index_wrapper

    if original_sim_index:
        @wraps(original_sim_index)
        def simulation_index_wrapper(*args, **kwargs):
            if is_regional_manager(current_user) or is_field_portal():
                return _restricted_simulation_index()
            return original_sim_index(*args, **kwargs)
        app.view_functions["simulation.index"] = simulation_index_wrapper

    if original_quarter:
        @wraps(original_quarter)
        def quarter_wrapper(*args, **kwargs):
            if is_regional_manager(current_user) or is_field_portal():
                return _restricted_quarter()
            return original_quarter(*args, **kwargs)
        app.view_functions["main.quarter"] = quarter_wrapper

    if original_territory_index:
        @wraps(original_territory_index)
        def territory_index_wrapper(*args, **kwargs):
            if is_regional_manager(current_user) and not access_enabled(current_user, "cross_region_assignments"):
                from app.services.period_service import PeriodService
                period = PeriodService.get_active_period()
                year = request.args.get("year", type=int) or period["year"]
                month = request.args.get("month", type=int) or period["month"]
                representatives = _scoped_representatives(active_only=False)
                rep_ids = {row.id for row in representatives}
                assignments = RepresentativeBrickAssignment.query.filter_by(year=year, month=month).order_by(
                    RepresentativeBrickAssignment.active.desc(), RepresentativeBrickAssignment.brick.asc()
                ).all()
                assignments = [row for row in assignments if row.representative_id in rep_ids]
                counts = {}
                for item in assignments:
                    bucket = counts.setdefault(item.representative_id, {"active": 0, "passive": 0, "total": 0})
                    bucket["active" if item.active else "passive"] += 1
                    bucket["total"] += 1
                return render_template(
                    "territory_management.html", representatives=representatives, assignments=assignments,
                    counts=counts, year=year, month=month, can_manage=True,
                )
            return original_territory_index(*args, **kwargs)
        app.view_functions["representatives.territory_management"] = territory_index_wrapper

    @app.context_processor
    def regional_manager_context():
        regional = bool(current_user.is_authenticated and is_regional_manager(current_user))
        field_scoped = bool(current_user.is_authenticated and is_field_portal())
        portal_manager_access = bool(current_user.is_authenticated and has_manager_access(current_user))
        return {
            "regional_manager_restricted": regional,
            "regional_manager_region": assigned_region(current_user) if regional else None,
            "field_portal_scoped": field_scoped,
            "field_portal_region": field_region() if field_scoped else None,
            "manager_type_label": manager_type_label(current_user) if current_user.is_authenticated else None,
            "can_view_manager_module": bool(current_user.is_authenticated and can_view_manager_module(current_user) and portal_manager_access),
            "can_manage_managers": bool(current_user.is_authenticated and can_manage_managers(current_user) and portal_manager_access),
            "settings_access": bool(current_user.is_authenticated and can_access_settings(current_user) and portal_manager_access),
            "can_reset_representative_passwords": bool(
                current_user.is_authenticated
                and portal_manager_access
                and (is_privileged_manager(current_user) or is_regional_manager(current_user))
            ),
            # Backward-compatible key used by older templates.
            "can_manage_region_managers": bool(current_user.is_authenticated and can_manage_managers(current_user) and portal_manager_access),
            "manager_access": bool(portal_manager_access and not regional),
            "access_permissions": {
                key: access_enabled(current_user, key)
                for key in (
                    "market_analysis", "ims_center", "region_assignments", "products", "targets",
                    "manual_matching", "prime_center", "prime_simulation", "q_analysis", "recovery",
                    "reports", "manager_module", "manage_managers", "cross_region_details",
                    "cross_region_assignments",
                )
            } if current_user.is_authenticated else {},
        }

    @app.before_request
    def enforce_manager_scope():
        if not current_user.is_authenticated:
            return None

        endpoint = request.endpoint or ""
        json_response = (
            request.is_json
            or endpoint.startswith("competition.")
            or (endpoint.startswith("simulation.") and request.method != "GET")
        )

        permission = _endpoint_permission(endpoint)
        if permission and (is_field_portal() or is_manager(current_user)) and not access_enabled(current_user, permission):
            return _deny_permission(json_response=json_response)

        if is_field_portal():
            forbidden_prefixes = ("settings.",)
            if endpoint == "representatives.index" and not is_privileged_manager(current_user):
                return _deny_field(json_response=json_response)
            if endpoint.startswith(forbidden_prefixes) or endpoint in {
                "representatives.add", "representatives.edit",
                "representatives.status", "representatives.save_assignment",
                "representatives.reset_password",
            }:
                return _deny_field(json_response=json_response)
            if endpoint == "regions.detail" and not can_access_region(current_user, (request.view_args or {}).get("region_key")):
                return _deny_region()
            if endpoint == "representatives.view":
                rep_id = int((request.view_args or {}).get("id") or 0)
                if not _request_rep_allowed(rep_id):
                    return _deny_region()
            if endpoint == "simulation.representative_info":
                rep_id = int((request.view_args or {}).get("rep_id") or 0)
                if not _request_rep_allowed(rep_id):
                    return _deny_region(json_response=True)
            if endpoint.startswith("simulation.") and request.method == "POST":
                rep_id = _json_rep_id()
                if rep_id and not _request_rep_allowed(rep_id):
                    return _deny_region(json_response=True)
            if endpoint == "main.quarter":
                rep_id = request.args.get("representative_id", type=int)
                if rep_id and not _request_rep_allowed(rep_id):
                    return _deny_region()
            if endpoint.startswith("competition."):
                rep_id = (
                    (request.view_args or {}).get("representative_id")
                    or (request.view_args or {}).get("rep_id")
                    or request.args.get("representative_id", type=int)
                    or request.args.get("rep_id", type=int)
                    or _json_rep_id()
                )
                if rep_id and not _request_rep_allowed(int(rep_id)):
                    return _deny_region(json_response=True)
            return None

        if not is_manager(current_user):
            return None

        if is_functional_manager(current_user):
            if endpoint.startswith("settings."):
                return _deny_settings(json_response=json_response)
            return None

        if not is_regional_manager(current_user):
            return None

        forbidden_prefixes = (
            "settings.",
        )
        if endpoint.startswith(forbidden_prefixes):
            return _deny_system(json_response=json_response)

        if endpoint in {"representatives.add", "representatives.edit", "representatives.status"}:
            return _deny_system(json_response=json_response)

        if endpoint == "representatives.save_assignment":
            rep_id = int((request.view_args or {}).get("id") or 0)
            representative = db.session.get(Representative, rep_id) if rep_id else None
            if not access_enabled(current_user, "cross_region_assignments") and not representative_in_region(
                representative, assigned_region(current_user)
            ):
                return _deny_region(json_response=json_response)

        if endpoint in {"representatives.territory_status", "representatives.territory_transfer"}:
            assignment_id = int((request.view_args or {}).get("assignment_id") or 0)
            assignment = db.session.get(RepresentativeBrickAssignment, assignment_id)
            source = db.session.get(Representative, assignment.representative_id) if assignment else None
            cross_assignment = access_enabled(current_user, "cross_region_assignments")
            if not cross_assignment and not representative_in_region(source, assigned_region(current_user)):
                return _deny_region(json_response=json_response)
            if endpoint == "representatives.territory_transfer":
                target_id = request.form.get("target_representative_id", type=int)
                target = db.session.get(Representative, target_id) if target_id else None
                if not cross_assignment and not representative_in_region(target, assigned_region(current_user)):
                    return _deny_region(json_response=json_response)

        if endpoint == "regions.detail":
            if not can_access_region(current_user, (request.view_args or {}).get("region_key")):
                return _deny_region()

        if endpoint == "representatives.view":
            rep_id = int((request.view_args or {}).get("id") or 0)
            if not _request_rep_allowed(rep_id):
                return _deny_region()

        if endpoint == "simulation.representative_info":
            rep_id = int((request.view_args or {}).get("rep_id") or 0)
            if not _request_rep_allowed(rep_id):
                return _deny_region(json_response=True)

        if endpoint.startswith("simulation.") and request.method == "POST":
            rep_id = _json_rep_id()
            if rep_id and not _request_rep_allowed(rep_id):
                return _deny_region(json_response=True)

        if endpoint == "main.quarter":
            rep_id = request.args.get("representative_id", type=int)
            if rep_id and not _request_rep_allowed(rep_id):
                return _deny_region()

        if endpoint.startswith("competition."):
            rep_id = (
                (request.view_args or {}).get("representative_id")
                or (request.view_args or {}).get("rep_id")
                or request.args.get("representative_id", type=int)
                or request.args.get("rep_id", type=int)
                or _json_rep_id()
            )
            if rep_id and not _request_rep_allowed(int(rep_id)):
                return _deny_region(json_response=True)
        return None

    @app.after_request
    def filter_regional_search(response):
        if request.endpoint == "representatives.search":
            return _filter_search_response(response)
        return response


manager_users_bp = Blueprint("manager_users", __name__, url_prefix="/manager-users")


def manager_module_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not can_view_manager_module(current_user) or not has_manager_access(current_user):
            flash("Yönetici Modülü yalnızca yönetici hesaplarına açıktır.", "warning")
            return redirect(url_for("dashboard.index"))
        return view(*args, **kwargs)
    return wrapped


def manager_mutation_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not has_manager_access(current_user) or not can_manage_managers(current_user):
            flash("Bu hesap yönetici ekleme veya düzenleme yetkisine sahip değildir.", "warning")
            return redirect(url_for("manager_users.index"))
        return view(*args, **kwargs)
    return wrapped


def _manager_rows():
    managers = User.query.filter(db.func.lower(User.role) == "manager").order_by(User.full_name.asc()).all()
    rows = []
    for user in managers:
        scope = _scope_for(user)
        rows.append({
            "user": user,
            "manager_type": manager_type(user),
            "manager_type_label": manager_type_label(user),
            "region_code": scope.region_code if scope else None,
            "editable": not is_privileged_manager(user),
        })
    return rows


def _validate_region(value):
    code = region_code(value)
    valid_codes = {item[0] for item in available_regions()}
    return code if code in valid_codes else None


def _validated_manager_type(value):
    kind = str(value or "").strip().casefold()
    return kind if kind in MANAGER_TYPES else None


@manager_users_bp.route("/", methods=["GET"])
@manager_module_required
def index():
    return render_template(
        "manager_users.html",
        managers=_manager_rows(),
        regions=available_regions(),
        manager_types=MANAGER_TYPES,
        can_edit=can_manage_managers(current_user),
    )


@manager_users_bp.route("/create", methods=["POST"])
@manager_mutation_required
def create():
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    kind = _validated_manager_type(request.form.get("manager_type"))
    code = _validate_region(request.form.get("region_code", "")) if kind == "region" else None

    if len(full_name) < 3 or "@" not in email or len(password) < 8 or not kind or (kind == "region" and not code):
        flash("Ad soyad, geçerli mail, en az 8 karakter şifre ve geçerli yönetici tipi zorunludur.", "warning")
        return redirect(url_for("manager_users.index"))
    if User.query.filter(db.func.lower(User.email) == email).first():
        flash("Bu e-posta adresi zaten kayıtlı.", "danger")
        return redirect(url_for("manager_users.index"))

    user = User(full_name=full_name, email=email, password=generate_password_hash(password), role="Manager", active=True)
    db.session.add(user)
    db.session.flush()
    db.session.add(RegionManagerScope(user_id=user.id, region_code=code, manager_type=kind))
    db.session.commit()
    from app.services.user_vault_service import UserVaultService
    UserVaultService.sync_from_primary()
    suffix = f" ({code})" if code else ""
    flash(f"{full_name} {MANAGER_TYPES[kind]} olarak oluşturuldu{suffix}.", "success")
    return redirect(url_for("manager_users.index"))


@manager_users_bp.route("/<int:user_id>/update", methods=["POST"])
@manager_mutation_required
def update(user_id):
    user = db.session.get(User, user_id)
    if user is None or str(user.role or "").casefold() != "manager" or is_privileged_manager(user):
        flash("Düzenlenebilir yönetici hesabı bulunamadı.", "danger")
        return redirect(url_for("manager_users.index"))

    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    kind = _validated_manager_type(request.form.get("manager_type"))
    code = _validate_region(request.form.get("region_code", "")) if kind == "region" else None
    duplicate = User.query.filter(db.func.lower(User.email) == email, User.id != user.id).first()
    if len(full_name) < 3 or "@" not in email or not kind or (kind == "region" and not code):
        flash("Ad soyad, geçerli mail ve geçerli yönetici tipi zorunludur.", "warning")
        return redirect(url_for("manager_users.index"))
    if duplicate:
        flash("Bu e-posta adresi başka bir kullanıcıda kayıtlı.", "danger")
        return redirect(url_for("manager_users.index"))
    if password and len(password) < 8:
        flash("Yeni şifre en az 8 karakter olmalıdır.", "warning")
        return redirect(url_for("manager_users.index"))

    user.full_name = full_name
    user.email = email
    if password:
        user.password = generate_password_hash(password)
    scope = _scope_for(user)
    if scope is None:
        scope = RegionManagerScope(user_id=user.id, region_code=code, manager_type=kind)
        db.session.add(scope)
    else:
        scope.region_code = code
        scope.manager_type = kind
    db.session.commit()
    from app.services.user_vault_service import UserVaultService
    UserVaultService.sync_from_primary()
    flash("Yönetici bilgileri güncellendi.", "success")
    return redirect(url_for("manager_users.index"))


@manager_users_bp.route("/<int:user_id>/toggle", methods=["POST"])
@manager_mutation_required
def toggle(user_id):
    user = db.session.get(User, user_id)
    if user is None or str(user.role or "").casefold() != "manager" or is_privileged_manager(user):
        flash("Düzenlenebilir yönetici hesabı bulunamadı.", "danger")
        return redirect(url_for("manager_users.index"))
    user.active = not user.active
    db.session.commit()
    from app.services.user_vault_service import UserVaultService
    UserVaultService.sync_from_primary()
    flash("Yönetici hesap durumu güncellendi.", "success")
    return redirect(url_for("manager_users.index"))
