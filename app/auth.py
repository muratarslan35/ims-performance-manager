from flask import Blueprint
from flask import render_template
from flask import request
from flask import redirect
from flask import url_for
from flask import flash

from flask_login import login_user
from flask_login import logout_user
from flask_login import login_required
from flask_login import current_user

from werkzeug.security import check_password_hash

from app.models import User

auth_bp = Blueprint(
    "auth",
    __name__
)


@auth_bp.route("/", methods=["GET", "POST"])
def login():

    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":

        email = request.form.get("email")

        password = request.form.get("password")

        user = User.query.filter_by(
            email=email
        ).first()

        if user and check_password_hash(
            user.password,
            password
        ):

            login_user(user)

            return redirect(
                url_for("main.dashboard")
            )

        flash(
            "Invalid email or password.",
            "danger"
        )

    return render_template(
        "login.html"
    )


@auth_bp.route("/logout")
@login_required
def logout():

    logout_user()

    return redirect(
        url_for("auth.login")
    )
