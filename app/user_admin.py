"""Owner-only user registry administration."""

from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.security import generate_password_hash

from app.access_control import can_manage_all_users
from app.extensions import db
from app.models import User
from app.services.ims_publication_service import ims_publication_receipts
from app.services.user_vault_service import UserVaultService


user_admin_bp = Blueprint("user_admin", __name__, url_prefix="/user-panel")
ALLOWED_ROLES = ("Admin", "Manager", "Representative")


def user_admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not can_manage_all_users(current_user):
            flash("Kullanıcı Paneli yalnızca yetkili sistem yöneticisine açıktır.", "warning")
            return redirect(url_for("dashboard.index"))
        return view(*args, **kwargs)
    return wrapped


@user_admin_bp.route("/", methods=["GET"])
@user_admin_required
def index():
    users = User.query.order_by(User.active.desc(), User.full_name.asc(), User.id.asc()).all()
    return render_template("user_admin.html", users=users, roles=ALLOWED_ROLES)


@user_admin_bp.route("/<int:user_id>/update", methods=["POST"])
@user_admin_required
def update(user_id):
    from app.region_manager import RegionManagerScope

    user = db.session.get(User, user_id)
    if user is None:
        flash("Kullanıcı bulunamadı.", "danger")
        return redirect(url_for("user_admin.index"))

    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    role = request.form.get("role", "").strip()
    password = request.form.get("password", "")
    active = request.form.get("active") == "1"

    if len(full_name) < 3 or "@" not in email or role not in ALLOWED_ROLES:
        flash("Ad soyad, geçerli e-posta ve kullanıcı rolü zorunludur.", "warning")
        return redirect(url_for("user_admin.index"))
    if password and len(password) < 8:
        flash("Yeni şifre en az 8 karakter olmalıdır.", "warning")
        return redirect(url_for("user_admin.index"))
    duplicate = User.query.filter(db.func.lower(User.email) == email, User.id != user.id).first()
    if duplicate:
        flash("Bu e-posta adresi başka bir kullanıcıda kayıtlı.", "danger")
        return redirect(url_for("user_admin.index"))

    editing_self = int(user.id) == int(current_user.id)
    previous_email = user.email
    user.full_name = full_name
    user.email = email
    user.phone = phone or None
    user.role = "Admin" if editing_self else role
    user.active = True if editing_self else active
    if password:
        user.password = generate_password_hash(password)

    scope = RegionManagerScope.query.filter_by(user_id=user.id).one_or_none()
    if user.role == "Manager" and scope is None:
        db.session.add(RegionManagerScope(
            user_id=user.id, manager_type="promotion", region_code=None
        ))
    elif user.role != "Manager" and scope is not None:
        db.session.delete(scope)

    db.session.commit()
    # The vault is an independent durable store. Remove the previous identity
    # before re-syncing so an e-mail correction cannot resurrect a stale login.
    UserVaultService.delete_user(user.id, previous_email)
    UserVaultService.sync_from_primary()
    flash("Kullanıcı bilgileri veritabanında güncellendi.", "success")
    return redirect(url_for("user_admin.index"))


@user_admin_bp.route("/<int:user_id>/delete", methods=["POST"])
@user_admin_required
def delete(user_id):
    from app.region_manager import RegionManagerScope

    user = db.session.get(User, user_id)
    if user is None:
        flash("Kullanıcı bulunamadı.", "danger")
        return redirect(url_for("user_admin.index"))
    if int(user.id) == int(current_user.id):
        flash("Oturum açtığınız yönetici hesabı silinemez.", "danger")
        return redirect(url_for("user_admin.index"))

    deleted_id, deleted_email, deleted_name = user.id, user.email, user.full_name
    RegionManagerScope.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    db.session.execute(
        ims_publication_receipts.delete().where(
            ims_publication_receipts.c.user_id == int(user.id)
        )
    )
    db.session.delete(user)
    db.session.commit()
    UserVaultService.delete_user(deleted_id, deleted_email)
    flash(f"{deleted_name} kullanıcısı kalıcı olarak silindi.", "success")
    return redirect(url_for("user_admin.index"))
