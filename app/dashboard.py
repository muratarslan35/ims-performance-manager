from flask import Blueprint
from flask import render_template

from flask_login import login_required

from app.services.dashboard_service import (
    DashboardService
)


dashboard_bp = Blueprint(

    "dashboard",

    __name__,

    url_prefix="/dashboard"

)


@dashboard_bp.route(

    "/"

)
@login_required
def index():

    service = DashboardService()

    dashboard = service.run()

    return render_template(

        "dashboard.html",

        dashboard=dashboard,

        total_products=dashboard[

            "total_products"

        ],

        total_representatives=dashboard[

            "total_representatives"

        ],

        total_targets=dashboard[

            "total_targets"

        ],

        total_uploads=dashboard[

            "total_uploads"

        ],

        completed_uploads=dashboard[

            "completed_uploads"

        ],

        failed_uploads=dashboard[

            "failed_uploads"

        ],

        processing_uploads=dashboard[

            "processing_uploads"

        ],

        last_upload=dashboard[

            "last_upload"

        ],

        latest_upload_date=dashboard[

            "latest_upload_date"

        ],

        latest_upload_status=dashboard[

            "latest_upload_status"

        ],

        latest_upload_file=dashboard[

            "latest_upload_file"

        ],

        prime_summary=dashboard[

            "prime_summary"

        ],

        quarter_summary=dashboard[

            "quarter_summary"

        ],

        recovery_summary=dashboard[

            "recovery_summary"

        ],

        ai_messages=dashboard[

            "ai_messages"

        ],

        risk_products=dashboard[

            "risk_products"

        ],

        critical_products=dashboard[

            "critical_products"

        ],

        warning_products=dashboard[

            "warning_products"

        ],

        healthy_products=dashboard[

            "healthy_products"

        ],

        overall_percent=dashboard["overall_percent"],
        overall_realization_tl=dashboard["overall_realization_tl"],
        overall_target_tl=dashboard["overall_target_tl"],
        product_performance=dashboard["product_performance"],
        total_ciro=dashboard["total_ciro"],
        top_representatives=dashboard["top_representatives"],
        monthly_trend=dashboard["monthly_trend"],
        market_share_trend=dashboard["market_share_trend"],
        city_performance=dashboard["city_performance"],
        active_quarter=dashboard["active_quarter"],
        recent_uploads=dashboard["recent_uploads"],
        ai_scores=dashboard["ai_scores"],

    )
