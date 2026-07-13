from flask import Blueprint
from flask import flash
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for

from flask_login import login_required

from app.extensions import db
from app.models import (
    Target,
    Representative,
    Product
)


targets_bp = Blueprint(

    "targets",

    __name__,

    url_prefix="/targets"

)


@targets_bp.route(

    "/"

)
@login_required
def index():

    targets = Target.query.order_by(

        Target.year.desc(),

        Target.month.desc()

    ).all()

    representatives = Representative.query.filter_by(

        active=True

    ).order_by(

        Representative.rep_name.asc()

    ).all()

    products = Product.query.filter_by(

        is_active=True

    ).order_by(

        Product.display_order.asc()

    ).all()

    return render_template(

        "targets.html",

        targets=targets,

        representatives=representatives,

        products=products

    )


@targets_bp.route(

    "/add",

    methods=["POST"]

)
@login_required
def add():

    try:

        target = Target(

            representative_id=int(

                request.form.get(

                    "representative_id"

                )

            ),

            product_id=int(

                request.form.get(

                    "product_id"

                )

            ),

            year=int(

                request.form.get(

                    "year"

                )

            ),

            month=int(

                request.form.get(

                    "month"

                )

            ),

            target_unit=float(

                request.form.get(

                    "target_unit",

                    0

                ) or 0

            ),

            target_tl=float(

                request.form.get(

                    "target_tl",

                    0

                ) or 0

            )

        )

        db.session.add(

            target

        )

        db.session.commit()

        flash(

            "Hedef başarıyla eklendi.",

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

            "targets.index"

        )

    )


@targets_bp.route(

    "/edit/<int:id>",

    methods=["POST"]

)
@login_required
def edit(

    id

):

    target = Target.query.get_or_404(

        id

    )

    try:

        target.target_unit = float(

            request.form.get(

                "target_unit",

                0

            ) or 0

        )

        target.target_tl = float(

            request.form.get(

                "target_tl",

                0

            ) or 0

        )

        db.session.commit()

        flash(

            "Hedef güncellendi.",

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

            "targets.index"

        )

    )

@targets_bp.route(

    "/delete/<int:id>",

    methods=["POST"]

)
@login_required
def delete(

    id

):

    target = Target.query.get_or_404(

        id

    )

    try:

        db.session.delete(

            target

        )

        db.session.commit()

        flash(

            "Hedef silindi.",

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

            "targets.index"

        )

    )


@targets_bp.route(

    "/view/<int:id>"

)
@login_required
def view(

    id

):

    target = Target.query.get_or_404(

        id

    )

    return render_template(

        "target_detail.html",

        target=target

    )


@targets_bp.route(

    "/api"

)
@login_required
def api():

    targets = Target.query.order_by(

        Target.year.desc(),

        Target.month.desc()

    ).all()

    return jsonify(

        {

            "success": True,

            "count": len(

                targets

            ),

            "targets": [

                {

                    "id": target.id,

                    "representative_id": target.representative_id,

                    "product_id": target.product_id,

                    "year": target.year,

                    "month": target.month,

                    "target_unit": target.target_unit,

                    "target_tl": target.target_tl

                }

                for target in targets

            ]

        }

    )


@targets_bp.route(

    "/health"

)
@login_required
def health():

    return jsonify(

        {

            "success": True,

            "module": "Targets",

            "version": "1.0.0",

            "statistics": {

                "total":

                    Target.query.count(),

                "representatives":

                    Representative.query.filter_by(

                        active=True

                    ).count(),

                "products":

                    Product.query.filter_by(

                        is_active=True

                    ).count()

            }

        }

    )
