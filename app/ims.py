from flask import Blueprint
from flask import render_template
from flask import request
from flask import redirect
from flask import url_for
from flask import flash
from flask_login import login_required

from werkzeug.utils import secure_filename

import os

from config import Config

ims_bp = Blueprint(
    "ims",
    __name__,
    url_prefix="/ims"
)


@ims_bp.route("/")
@login_required
def index():

    return render_template(
        "ims.html"
    )


@ims_bp.route("/upload", methods=["POST"])
@login_required
def upload():

    if "file" not in request.files:

        flash(
            "Dosya seçilmedi.",
            "danger"
        )

        return redirect(
            url_for("ims.index")
        )

    file = request.files["file"]

    if file.filename == "":

        flash(
            "Dosya seçilmedi.",
            "danger"
        )

        return redirect(
            url_for("ims.index")
        )

    filename = secure_filename(
        file.filename
    )

    path = os.path.join(
        Config.UPLOAD_FOLDER,
        filename
    )

    file.save(path)

    flash(
        "IMS dosyası başarıyla yüklendi.",
        "success"
    )

    return redirect(
        url_for("ims.index")
    )
