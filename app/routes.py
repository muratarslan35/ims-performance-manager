from flask import Blueprint, redirect, render_template, url_for

from flask_login import current_user
from flask_login import login_required

main_bp = Blueprint(
    "main",
    __name__
)


@main_bp.route("/")
@login_required
def home():
    return redirect(url_for("dashboard.index"))


@main_bp.route("/dashboard")
@login_required
def dashboard():

    return redirect(
        url_for("dashboard.index")
    )


@main_bp.route("/prime")
@login_required
def prime():

    return render_template(
        "prime.html",
        user=current_user
    )


@main_bp.route("/reports")
@login_required
def reports():

    return render_template(
        "reports.html",
        user=current_user
    )


@main_bp.route("/settings")
@login_required
def settings():

    return render_template(
        "settings.html",
        user=current_user
    )
