from flask import Blueprint
from flask import render_template
from flask import request
from flask import redirect
from flask import url_for
from flask import flash

from flask_login import login_required

from app.extensions import db
from app.models import Representative

representatives_bp = Blueprint(
    "representatives",
    __name__,
    url_prefix="/representatives"
)


@representatives_bp.route("/")
@login_required
def index():

    representatives = Representative.query.order_by(
        Representative.rep_name.asc()
    ).all()

    return render_template(
        "representatives.html",
        representatives=representatives
    )


@representatives_bp.route("/add", methods=["POST"])
@login_required
def add():

    representative = Representative(

        rep_code=request.form.get("rep_code"),

        ims_code=request.form.get("ims_code"),

        sap_code=request.form.get("sap_code"),

        rep_name=request.form.get("rep_name"),

        region=request.form.get("region"),

        city=request.form.get("city"),

        district=request.form.get("district"),

        manager=request.form.get("manager"),

        team=request.form.get("team"),

        active=True

    )

    db.session.add(representative)

    db.session.commit()

    flash(
        "Temsilci başarıyla eklendi.",
        "success"
    )

    return redirect(
        url_for("representatives.index")
    )


@representatives_bp.route("/status/<int:id>")
@login_required
def status(id):

    representative = Representative.query.get_or_404(id)

    representative.active = not representative.active

    db.session.commit()

    if representative.active:

        flash(
            "Temsilci aktif edildi.",
            "success"
        )

    else:

        flash(
            "Temsilci pasif edildi.",
            "warning"
        )

    return redirect(
        url_for("representatives.index")
    )


@representatives_bp.route("/edit/<int:id>", methods=["POST"])
@login_required
def edit(id):

    representative = Representative.query.get_or_404(id)

    representative.rep_code = request.form.get("rep_code")

    representative.ims_code = request.form.get("ims_code")

    representative.sap_code = request.form.get("sap_code")

    representative.rep_name = request.form.get("rep_name")

    representative.region = request.form.get("region")

    representative.city = request.form.get("city")

    representative.district = request.form.get("district")

    representative.manager = request.form.get("manager")

    representative.team = request.form.get("team")

    db.session.commit()

    flash(
        "Temsilci bilgileri güncellendi.",
        "success"
    )

    return redirect(
        url_for("representatives.index")
    )
