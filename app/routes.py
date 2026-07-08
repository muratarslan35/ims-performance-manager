from flask import Blueprint
from flask import render_template

main_bp = Blueprint(
    "main",
    __name__
)


@main_bp.route("/")
def login():

    return render_template(
        "login.html"
    )


@main_bp.route("/dashboard")
def dashboard():

    return render_template(
        "dashboard.html"
    )
