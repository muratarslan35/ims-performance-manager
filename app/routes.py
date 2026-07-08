from flask import Blueprint
from flask import render_template
from flask_login import login_required

main_bp = Blueprint(
    "main",
    __name__,
)


@main_bp.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")


@main_bp.route("/products")
def products():
    return render_template("products.html")


@main_bp.route("/targets")
def targets():
    return render_template("targets.html")


@main_bp.route("/ims")
def ims():
    return render_template("ims.html")


@main_bp.route("/prime")
def prime():
    return render_template("prime.html")


@main_bp.route("/reports")
def reports():
    return render_template("reports.html")


@main_bp.route("/settings")
def settings():
    return render_template("settings.html")
