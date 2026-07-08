from flask import Blueprint
from flask import render_template

from flask_login import login_required

from app.models import (
    Product,
    Representative,
    IMSUpload,
    Target
)

dashboard_bp = Blueprint(
    "dashboard",
    __name__,
    url_prefix="/dashboard"
)


@dashboard_bp.route("/")
@login_required
def index():

    total_products = Product.query.filter_by(
        is_active=True
    ).count()

    total_representatives = Representative.query.filter_by(
        active=True
    ).count()

    total_targets = Target.query.count()

    last_upload = IMSUpload.query.order_by(
        IMSUpload.uploaded_at.desc()
    ).first()

    return render_template(

        "dashboard.html",

        total_products=total_products,

        total_representatives=total_representatives,

        total_targets=total_targets,

        last_upload=last_upload

    )
