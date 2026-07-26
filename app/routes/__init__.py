from flask import Blueprint
from flask import redirect
from flask import render_template
from flask import url_for

from flask_login import current_user
from flask_login import login_required


main_bp = Blueprint(
    "main",
    __name__
)


@main_bp.route("/")
@login_required
def home():
    return render_template(
        "dashboard.html",
        user=current_user
    )


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


@main_bp.route("/quarter")
@login_required
def quarter():
    return redirect(
        url_for("simulation.index")
    )


@main_bp.route("/recovery")
@login_required
def recovery():
    return redirect(
        url_for("simulation.index")
    )


@main_bp.route("/settings")
@login_required
def settings():
    return redirect(
        url_for("settings.index")
    )
