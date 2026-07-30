from flask import Blueprint
from flask import flash
from flask import redirect
from flask import render_template
from flask import current_app
from flask import request
from flask import url_for
from urllib.parse import urlparse

from flask_login import current_user
from flask_login import login_required
from flask_login import login_user
from flask_login import logout_user

from itsdangerous import BadSignature
from itsdangerous import SignatureExpired
from itsdangerous import URLSafeTimedSerializer
from werkzeug.security import check_password_hash
from werkzeug.security import generate_password_hash

from app.extensions import db

from app.models import User

auth_bp = Blueprint(
    "auth",
    __name__
)


def _reset_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def _password_reset_token(user):
    return _reset_serializer().dumps({"user_id": user.id}, salt="password-reset")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():

    if current_user.is_authenticated:
        return redirect(
            url_for("main.dashboard")
        )

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        if not email or not password:

            flash(
                "E-posta ve şifre zorunludur.",
                "warning"
            )

            return render_template(
                "login.html"
            )

        user = User.query.filter_by(
            email=email
        ).first()

        if user is None:

            flash(
                "Kullanıcı bulunamadı.",
                "danger"
            )

            return render_template(
                "login.html"
            )

        if not user.active:

            flash(
                "Kullanıcı pasif durumda.",
                "danger"
            )

            return render_template(
                "login.html"
            )

        if not check_password_hash(
            user.password,
            password
        ):

            flash(
                "Şifre hatalı.",
                "danger"
            )

            return render_template(
                "login.html"
            )

        login_user(
            user,
            remember=True
        )

        flash(
            f"Hoş geldiniz {user.full_name}",
            "success"
        )

        next_page = request.args.get("next") or request.form.get("next")
        if next_page:
            parsed_next = urlparse(next_page)
            if (not parsed_next.scheme
                    and not parsed_next.netloc
                    and parsed_next.path.startswith("/")):
                return redirect(parsed_next.path)

        return redirect(
            url_for("main.dashboard")
        )

    return render_template(
        "login.html"
    )


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")

        if not full_name or not email or not password or not password_confirm:
            flash("Lütfen tüm zorunlu alanları doldurun.", "warning")
        elif len(full_name) < 3:
            flash("Ad soyad en az 3 karakter olmalıdır.", "warning")
        elif "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            flash("Geçerli bir e-posta adresi girin.", "warning")
        elif len(password) < 8:
            flash("Şifre en az 8 karakter olmalıdır.", "warning")
        elif password != password_confirm:
            flash("Şifre ve şifre tekrarı aynı olmalıdır.", "warning")
        elif User.query.filter_by(email=email).first():
            flash("Bu e-posta adresi zaten kayıtlı.", "danger")
        else:
            user = User(
                full_name=full_name,
                email=email,
                password=generate_password_hash(password),
                role="Representative",
                active=True,
            )
            db.session.add(user)
            db.session.commit()
            login_user(user, remember=True)
            flash("Hesabınız oluşturuldu. Hoş geldiniz!", "success")
            return redirect(url_for("main.dashboard"))

    return render_template("register.html")


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    reset_url = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            token = _password_reset_token(user)
            reset_url = url_for("auth.reset_password", token=token, _external=True)
            current_app.logger.info("Password reset requested for user_id=%s", user.id)
        flash("E-posta adresi kayıtlıysa şifre yenileme bağlantısı hazırlanmıştır.", "success")

    return render_template("forgot_password.html", reset_url=reset_url)


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        data = _reset_serializer().loads(
            token,
            salt="password-reset",
            max_age=current_app.config.get("RESET_TOKEN_MAX_AGE", 3600),
        )
        user = db.session.get(User, data.get("user_id"))
    except (BadSignature, SignatureExpired):
        user = None

    if user is None:
        flash("Şifre yenileme bağlantısı geçersiz veya süresi dolmuş.", "danger")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")
        if len(password) < 8:
            flash("Şifre en az 8 karakter olmalıdır.", "warning")
        elif password != password_confirm:
            flash("Şifre ve şifre tekrarı aynı olmalıdır.", "warning")
        else:
            user.password = generate_password_hash(password)
            db.session.commit()
            flash("Şifreniz güncellendi. Yeni şifrenizle giriş yapabilirsiniz.", "success")
            return redirect(url_for("auth.login"))

    return render_template("reset_password.html")


@auth_bp.route("/logout")
@login_required
def logout():

    logout_user()

    flash(
        "Başarıyla çıkış yapıldı.",
        "success"
    )

    return redirect(
        url_for("auth.login")
    )
