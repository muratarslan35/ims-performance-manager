from flask import Blueprint
from flask import flash
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for

from flask_login import current_user
from flask_login import login_required
from flask_login import login_user
from flask_login import logout_user

from werkzeug.security import check_password_hash

from app.models import User

auth_bp = Blueprint(
    "auth",
    __name__
)


@auth_bp.route("/", methods=["GET", "POST"])
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

        return redirect(
            url_for("main.dashboard")
        )

    return render_template(
        "login.html"
    )


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
