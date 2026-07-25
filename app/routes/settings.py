from flask import Blueprint
from flask import flash
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for

from flask_login import login_required

from app.extensions import db
from app.models import Setting


settings_bp = Blueprint(

    "settings",

    __name__,

    url_prefix="/settings"

)


@settings_bp.route(

    "/"

)
@login_required
def index():

    settings = Setting.query.order_by(

        Setting.setting_key.asc()

    ).all()

    return render_template(

        "settings.html",

        settings=settings

    )


@settings_bp.route(

    "/save",

    methods=["POST"]

)
@login_required
def save():

    try:

        for item in Setting.query.all():

            value = request.form.get(

                item.setting_key

            )

            if value is None:

                continue

            item.setting_value = value

        db.session.commit()

        flash(

            "Ayarlar güncellendi.",

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

            "settings.index"

        )

    )


@settings_bp.route(

    "/api"

)
@login_required
def api():

    settings = Setting.query.order_by(

        Setting.setting_key.asc()

    ).all()

    return jsonify(

        {

            "success": True,

            "count": len(

                settings

            ),

            "settings": [

                {

                    "id": item.id,

                    "key": item.setting_key,

                    "value": item.setting_value,

                    "description": item.description

                }

                for item in settings

            ]

        }
  @settings_bp.route(

    "/health"

)
@login_required
def health():

    return jsonify(

        {

            "success": True,

            "module": "Settings",

            "version": "1.0.0",

            "statistics": {

                "total":

                    Setting.query.count()

            }

        }

    )


@settings_bp.route(

    "/reset",

    methods=["POST"]

)
@login_required
def reset():

    try:

        defaults = {

            "MAIN_PRIME": "50000",

            "CIRO_PRIME": "20000",

            "PRIME_STEP": "5",

            "STEP_AMOUNT": "2500",

            "MAX_PRIME_PERCENT": "140",

            "MIN_PRIME_PERCENT": "100",

            "TARGET_75": "75",

            "TARGET_90": "90",

            "TARGET_100": "100"

        }

        for key, value in defaults.items():

            setting = Setting.query.filter_by(

                setting_key=key

            ).first()

            if setting:

                setting.setting_value = value

            else:

                db.session.add(

                    Setting(

                        setting_key=key,

                        setting_value=value,

                        description="Sistem Varsayılanı"

                    )

                )

        db.session.commit()

        flash(

            "Varsayılan ayarlar yüklendi.",

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

            "settings.index"

        )

    )
