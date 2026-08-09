from flask import Blueprint
from flask import current_app
from flask import flash
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for

from flask_login import current_user
from flask_login import login_required

from werkzeug.utils import secure_filename

from app.models import IMSUpload

from app.services.dashboard_service import (
    DashboardService
)
from app.services.ims_import_service import (
    IMSImportService
)


ims_bp = Blueprint(

    "ims",

    __name__,

    url_prefix="/ims"

)


@ims_bp.route(

    "/"

)
@login_required
def index():

    uploads = IMSUpload.query.order_by(

        IMSUpload.uploaded_at.desc()

    ).all()

    # TEMP DEBUG
    dashboard = {}
    # dashboard = {}

    return render_template(

        "ims.html",

        uploads=uploads,

        dashboard=dashboard

    )


@ims_bp.route(

    "/upload",

    methods=["POST"]

)
@login_required
def upload():

    file = request.files.get(

        "file"

    )

    if file is None or file.filename == "":

        flash(

            "Lütfen bir IMS dosyası seçiniz.",

            "warning"

        )

        return redirect(

            url_for(

                "ims.index"

            )

        )

    filename = secure_filename(

        file.filename

    )

    upload_path = current_app.config["UPLOAD_FOLDER"] / filename

    try:

        file.save(

            upload_path

        )

        year = int(

            request.form.get(

                "year"

            )

        )

        month = int(

            request.form.get(

                "month"

            )

        )

        service = IMSImportService(

            file_path=upload_path,

            uploaded_by=current_user.full_name

        )

        result = service.run(

            year=year,

            month=month,

            clear_before_import=False

        )

        if result["success"]:

            flash(

                f"{filename} başarıyla içe aktarıldı.",

                "success"

            )

            if result.get(

                "warnings"

            ):

                flash(

                    f"{len(result['warnings'])} uyarı oluştu.",

                    "warning"

                )

        else:

            flash(

                "\n".join(

                    result.get(

                        "errors",

                        [

                            "İçe aktarma başarısız."

                        ]

                    )

                ),

                "danger"

            )

    except Exception as exc:

        flash(

            f"IMS içe aktarılırken hata oluştu: {exc}",

            "danger"

        )

    return redirect(

        url_for(

            "ims.index"

        )

    )
