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

from app.models import Representative, User

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

    regions = (
        db.session.query(Representative.region, Representative.city)
        .filter(Representative.region.isnot(None), Representative.city.isnot(None))
        .distinct()
        .order_by(Representative.region.asc(), Representative.city.asc())
        .all()
    )

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        selected_region = request.form.get("region", "").strip()
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")

        if not full_name or not email or not password or not password_confirm or not selected_region:
            flash("Lütfen tüm zorunlu alanları doldurun.", "warning")
        elif selected_region not in {region for region, _ in regions}:
            flash("Lütfen listeden geçerli bir bölge seçin.", "warning")
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
                phone=phone or None,
                password=generate_password_hash(password),
                role="Representative",
                active=True,
            )
            db.session.add(user)
            # Registration owns account credentials; master representative
            # contact data is updated only on an exact normalized name match.
            # This prevents a similar-looking name from changing another
            # representative's card.
            from app.services.alias_service import AliasService
            normalized_name = AliasService.normalize(full_name)
            matches = [rep for rep in Representative.query.all() if AliasService.normalize(rep.rep_name) == normalized_name]
            representative = matches[0] if len(matches) == 1 and matches[0].region == selected_region else None
            if representative is None and not matches:
                suggestion = AliasService.find_representative(full_name)
                candidate = suggestion.get("object") if suggestion.get("matched") else None
                if candidate is not None and candidate.region == selected_region:
                    representative = candidate
            if representative is not None:
                representative.email = email
                if phone:
                    representative.phone = phone
            db.session.commit()
            from app.services.user_vault_service import UserVaultService
            UserVaultService.sync_from_primary()
            login_user(user, remember=True)
            flash("Hesabınız oluşturuldu. Hoş geldiniz!", "success")
            return redirect(url_for("main.dashboard"))

    return render_template("register.html", regions=regions)


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
            from app.services.user_vault_service import UserVaultService
            UserVaultService.sync_from_primary()
            flash("Şifreniz güncellendi. Yeni şifrenizle giriş yapabilirsiniz.", "success")
            return redirect(url_for("auth.login"))

    return render_template("reset_password.html")

@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    from app.services.alias_service import AliasService
    regions=db.session.query(Representative.region,Representative.city).filter(Representative.region.isnot(None),Representative.city.isnot(None)).distinct().order_by(Representative.region.asc(),Representative.city.asc()).all()
    representative=next((rep for rep in Representative.query.all() if AliasService.normalize(rep.rep_name)==AliasService.normalize(current_user.full_name)),None)
    if request.method=="POST":
        if request.form.get("action")=="password":
            current_password,password,confirm=request.form.get("current_password",""),request.form.get("password",""),request.form.get("password_confirm","")
            if not check_password_hash(current_user.password,current_password): flash("Mevcut şifre doğrulanamadı.","danger")
            elif len(password)<8 or password!=confirm: flash("Yeni şifre en az 8 karakter olmalı ve tekrarıyla aynı olmalıdır.","warning")
            else:
                current_user.password=generate_password_hash(password);db.session.commit()
                from app.services.user_vault_service import UserVaultService
                UserVaultService.sync_from_primary();flash("Şifreniz güncellendi.","success")
        else:
            full_name,email,phone,region=request.form.get("full_name","").strip(),request.form.get("email","").strip().lower(),request.form.get("phone","").strip(),request.form.get("region","").strip();duplicate=User.query.filter(User.email==email,User.id!=current_user.id).first()
            if not full_name or not email: flash("Ad soyad ve e-posta zorunludur.","warning")
            elif duplicate: flash("Bu e-posta başka bir hesapta kullanılıyor.","danger")
            elif region and region not in {code for code,_ in regions}: flash("Geçerli bir bölge seçin.","warning")
            else:
                current_user.full_name,current_user.email,current_user.phone=full_name,email,phone or None
                if representative is not None:
                    representative.email,representative.phone=email,phone or representative.phone
                    if region: representative.region,representative.city=region,next((city for code,city in regions if code==region),representative.city)
                db.session.commit()
                from app.services.user_vault_service import UserVaultService
                UserVaultService.sync_from_primary();flash("Profil bilgileriniz güncellendi.","success")
    return render_template("profile.html",regions=regions,representative=representative)


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
