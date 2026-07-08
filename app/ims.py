from pathlib import Path

from flask import Blueprint
from flask import flash
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for

from flask_login import login_required

from werkzeug.utils import secure_filename

from config import Config

from app.ims_reader import IMSReader
from app.models import IMSUpload
from app.extensions import db

ims_bp = Blueprint(
    "ims",
    __name__,
    url_prefix="/ims"
)


@ims_bp.route("/")
@login_required
def index():

    uploads = IMSUpload.query.order_by(
        IMSUpload.uploaded_at.desc()
    ).all()

    return render_template(
        "ims.html",
        uploads=uploads
    )


@ims_bp.route("/upload", methods=["POST"])
@login_required
def upload():

    file = request.files.get("file")

    if file is None or file.filename == "":

        flash(
            "Lütfen bir IMS dosyası seçiniz.",
            "warning"
        )

        return redirect(
            url_for("ims.index")
        )

    filename = secure_filename(file.filename)

    upload_path = (
        Config.UPLOAD_FOLDER /
        filename
    )

    file.save(upload_path)

    try:

        reader = IMSReader(upload_path)

        sheet_list = reader.get_sheet_names()

        upload = IMSUpload(

            file_name=filename

        )

        db.session.add(upload)

        db.session.commit()

        print("\n========== IMS ==========")

        for sheet in sheet_list:

            print(sheet)

        print("=========================\n")

        flash(

            f"{filename} başarıyla yüklendi. ({len(sheet_list)} çalışma sayfası bulundu)",

            "success"

        )

    except Exception as error:

        flash(

            f"Hata : {error}",

            "danger"

        )

    return redirect(
        url_for("ims.index")
    )
