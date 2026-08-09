from flask import Blueprint
from flask import flash
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for

from flask_login import login_required

from app.extensions import db
from app.models import Representative, RepresentativeBrickAssignment


representatives_bp = Blueprint(

    "representatives",

    __name__,

    url_prefix="/representatives"

)


@representatives_bp.route(

    "/"

)
@login_required
def index():

    representatives = Representative.query.order_by(

        Representative.rep_name.asc()

    ).all()

    return render_template(

        "representatives.html",

        representatives=representatives

    )


@representatives_bp.route(

    "/add",

    methods=["POST"]

)
@login_required
def add():

    try:

        representative = Representative(

            rep_code=request.form.get(

                "rep_code"

            ).strip(),

            ims_code=request.form.get(

                "ims_code"

            ).strip(),

            sap_code=request.form.get(

                "sap_code"

            ).strip(),

            rep_name=request.form.get(

                "rep_name"

            ).strip(),

            region=request.form.get(

                "region"

            ),

            city=request.form.get(

                "city"

            ),

            district=request.form.get(

                "district"

            ),

            territory=request.form.get(

                "territory"

            ),

            manager=request.form.get(

                "manager"

            ),

            team=request.form.get(

                "team"

            ),

            email=request.form.get(

                "email"

            ),

            phone=request.form.get(

                "phone"

            ),

            active=True

        )

        db.session.add(

            representative

        )

        db.session.commit()

        flash(

            "Temsilci başarıyla eklendi.",

            "success"

        )

    except Exception as exc:

        db.session.rollback()

        flash(

            str(

                exc

            ),

            "danger"

        )

    return redirect(

        url_for(

            "representatives.index"

        )

    )


@representatives_bp.route(

    "/edit/<int:id>",

    methods=["POST"]

)
@login_required
def edit(

    id

):

    representative = Representative.query.get_or_404(

        id

    )

    try:

        representative.rep_code = request.form.get(

            "rep_code"

        ).strip()

        representative.ims_code = request.form.get(

            "ims_code"

        ).strip()

        representative.sap_code = request.form.get(

            "sap_code"

        ).strip()

        representative.rep_name = request.form.get(

            "rep_name"

        ).strip()

        representative.region = request.form.get(

            "region"

        )

        representative.city = request.form.get(

            "city"

        )

        representative.district = request.form.get(

            "district"

        )

        representative.territory = request.form.get(

            "territory"

        )

        representative.manager = request.form.get(

            "manager"

        )

        representative.team = request.form.get(

            "team"

        )

        representative.email = request.form.get(

            "email"

        )

        representative.phone = request.form.get(

            "phone"

        )

        db.session.commit()

        flash(

            "Temsilci bilgileri güncellendi.",

            "success"

        )

    except Exception as exc:

        db.session.rollback()

        flash(

            str(

                exc

            ),

            "danger"

        )

    return redirect(

        url_for(

            "representatives.index"

        )

    )

@representatives_bp.route(

    "/status/<int:id>"

)
@login_required
def status(

    id

):

    representative = Representative.query.get_or_404(

        id

    )

    try:

        representative.active = (

            not representative.active

        )

        db.session.commit()

        flash(

            "Temsilci durumu güncellendi.",

            "success"

        )

    except Exception as exc:

        db.session.rollback()

        flash(

            str(

                exc

            ),

            "danger"

        )

    return redirect(

        url_for(

            "representatives.index"

        )

    )


@representatives_bp.route(

    "/view/<int:id>"

)
@login_required
def view(

    id

):

    representative = Representative.query.get_or_404(

        id

    )

    latest = RepresentativeBrickAssignment.query.order_by(RepresentativeBrickAssignment.year.desc(), RepresentativeBrickAssignment.month.desc()).first()
    year = request.args.get("year", type=int) or (latest.year if latest else None)
    month = request.args.get("month", type=int) or (latest.month if latest else None)
    assignments = RepresentativeBrickAssignment.query.filter_by(representative_id=id, year=year, month=month).order_by(RepresentativeBrickAssignment.brick).all() if year and month else []
    return render_template("representative_detail.html", representative=representative, assignments=assignments, year=year, month=month)


@representatives_bp.route("/view/<int:id>/assignments", methods=["POST"])
@login_required
def save_assignment(id):
    representative = Representative.query.get_or_404(id)
    try:
        year, month, brick = int(request.form["year"]), int(request.form["month"]), request.form["brick"].strip()
        assignment = RepresentativeBrickAssignment.query.filter_by(
            year=year, month=month, brick=brick, representative_id=representative.id
        ).first()
        if assignment is None:
            assignment = RepresentativeBrickAssignment(year=year, month=month, brick=brick)
            db.session.add(assignment)
        assignment.representative_id, assignment.source = representative.id, "MANUAL"
        assignment.quarter = f"Q{((month - 1) // 3) + 1}"
        db.session.commit()
        flash("Dönemsel brick ataması kaydedildi.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("representatives.view", id=id, year=request.form.get("year"), month=request.form.get("month")))


@representatives_bp.route(

    "/api"

)
@login_required
def api():

    representatives = Representative.query.order_by(

        Representative.rep_name.asc()

    ).all()

    return jsonify(

        {

            "success": True,

            "count": len(

                representatives

            ),

            "representatives": [

                {

                    "id": representative.id,

                    "rep_code": representative.rep_code,

                    "ims_code": representative.ims_code,

                    "sap_code": representative.sap_code,

                    "rep_name": representative.rep_name,

                    "region": representative.region,

                    "city": representative.city,

                    "district": representative.district,

                    "territory": representative.territory,

                    "manager": representative.manager,

                    "team": representative.team,

                    "email": representative.email,

                    "phone": representative.phone,

                    "active": representative.active

                }

                for representative in representatives

            ]

        }

    )


@representatives_bp.route(

    "/health"

)
@login_required
def health():

    return jsonify(

        {

            "success": True,

            "module": "Representatives",

            "version": "1.0.0",

            "statistics": {

                "total":

                    Representative.query.count(),

                "active":

                    Representative.query.filter_by(

                        active=True

                    ).count(),

                "inactive":

                    Representative.query.filter_by(

                        active=False

                    ).count()

            }

        }

    )
