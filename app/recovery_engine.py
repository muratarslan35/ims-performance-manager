from calendar import monthrange
from datetime import date

from app.extensions import db

from app.models import (
    IMSSummary,
    RecoverySummary,
    Target,
    Product
)


class RecoveryEngine:

    QUARTERS = {

        1: [1, 2, 3],
        2: [4, 5, 6],
        3: [7, 8, 9],
        4: [10, 11, 12]

    }

    def __init__(

        self,

        representative_id,

        year,

        quarter,

        today=None,

        overrides=None

    ):

        self.rep_id = representative_id

        self.year = year

        self.quarter = quarter

        self.months = self.QUARTERS[quarter]

        self.today = today or date.today()

        self.overrides = overrides or {}

    def get_month_data(

        self,

        product_id,

        month

    ):

        target = Target.query.filter_by(

            representative_id=self.rep_id,

            product_id=product_id,

            year=self.year,

            month=month

        ).first()

        summary = IMSSummary.query.filter_by(

            representative_id=self.rep_id,

            product_id=product_id,

            year=self.year,

            month=month

        ).first()

        target_box = 0

        target_tl = 0

        realization_box = 0

        realization_tl = 0

        if target:

            target_box = target.unit_target

            target_tl = target.tl_target

        if summary:

            realization_box = summary.unit

            realization_tl = summary.tl

        override = self.overrides.get(

            product_id

        )

        if override:

            realization_box = override.get(

                "unit",

                realization_box

            )

            realization_tl = override.get(

                "tl",

                realization_tl

            )

        return {

            "month": month,

            "target_box": target_box,

            "target_tl": target_tl,

            "realization_box": realization_box,

            "realization_tl": realization_tl,

            "difference_box":

                realization_box -

                target_box,

            "difference_tl":

                realization_tl -

                target_tl

        }

    def analyze_product(

        self,

        product_id

    ):

        months = self.get_product_data(

            product_id

        )

        carry_box = 0

        carry_tl = 0

        timeline = []

        total_target_box = 0

        total_realization_box = 0

        total_target_tl = 0

        total_realization_tl = 0

        for item in months:

            carry_box += item["difference_box"]

            carry_tl += item["difference_tl"]

            total_target_box += item["target_box"]

            total_realization_box += item["realization_box"]

            total_target_tl += item["target_tl"]

            total_realization_tl += item["realization_tl"]

            timeline.append(

                {

                    "month": item["month"],

                    "target_box": item["target_box"],

                    "realization_box": item["realization_box"],

                    "carry_box": carry_box,

                    "target_tl": item["target_tl"],

                    "realization_tl": item["realization_tl"],

                    "carry_tl": carry_tl

                }

            )

        remaining_box = abs(

            carry_box

        ) if carry_box < 0 else 0

        remaining_tl = abs(

            carry_tl

        ) if carry_tl < 0 else 0

        projected_percent = 0

        if total_target_tl > 0:

            projected_percent = round(

                (

                    total_realization_tl /

                    total_target_tl

                ) * 100,

                2

            )

        current_month = self.today.month

        days_left = 1

        if current_month in self.months:

            last_day = monthrange(

                self.year,

                current_month

            )[1]

            days_left = max(

                1,

                last_day -

                self.today.day +

                1

            )

        daily_need = round(

            remaining_box /

            days_left,

            2

        )

        projected_box = total_realization_box

        if current_month in self.months:

            current = next(

                (

                    x

                    for x in months

                    if x["month"] == current_month

                ),

                None

            )

            if current:

                elapsed = max(

                    1,

                    self.today.day

                )

                rate = (

                    current["realization_box"]

                    /

                    elapsed

                )

                projected_box += (

                    rate *

                    days_left

                )

        risk_score = 100

        if remaining_box > 0:

            ratio = (

                remaining_box /

                max(

                    total_target_box,

                    1

                )

            )

            risk_score = max(

                0,

                100 -

                int(

                    ratio * 100

                )

            )

        return {

            "timeline": timeline,

            "carry_box": carry_box,

            "carry_tl": carry_tl,

            "remaining_box": remaining_box,

            "remaining_tl": remaining_tl,

            "daily_need": round(

                daily_need,

                2

            ),

            "projected_box": round(

                projected_box,

                2

            ),

            "projected_percent": projected_percent,

            "risk_score": risk_score,

            "target_box": total_target_box,

            "realization_box": total_realization_box,

            "target_tl": total_target_tl,

            "realization_tl": total_realization_tl

        }

    def save_summary(

        self,

        product_id,

        result

    ):

        # Simülasyon modunda veritabanına yazma
        if self.overrides:

            return

        summary = RecoverySummary.query.filter_by(

            representative_id=self.rep_id,

            product_id=product_id,

            year=self.year,

            quarter=self.quarter

        ).first()

        if summary is None:

            summary = RecoverySummary(

                representative_id=self.rep_id,

                product_id=product_id,

                year=self.year,

                quarter=self.quarter

            )

            db.session.add(summary)

        summary.remaining_box = result["remaining_box"]

        summary.remaining_tl = result["remaining_tl"]

        summary.carry_box = result["carry_box"]

        summary.carry_tl = result["carry_tl"]

        summary.daily_need = result["daily_need"]

        summary.projected_box = result["projected_box"]

        summary.projected_percent = result["projected_percent"]

        summary.risk_score = result["risk_score"]

        if result["remaining_box"] <= 0:

            summary.status = "Tamamlandı"

        elif result["risk_score"] >= 80:

            summary.status = "Güvenli"

        elif result["risk_score"] >= 60:

            summary.status = "Takip"

        elif result["risk_score"] >= 40:

            summary.status = "Riskli"

        else:

            summary.status = "Kritik"


    def simulate(

        self,

        product_id,

        additional_box=0,

        additional_tl=0

    ):

        result = self.analyze_product(

            product_id

        )

        result["remaining_box"] = max(

            0,

            result["remaining_box"] -

            additional_box

        )

        result["remaining_tl"] = max(

            0,

            result["remaining_tl"] -

            additional_tl

        )

        result["can_close"] = (

            result["remaining_box"] == 0

        )

        return result


    def run(

        self

    ):

        dashboard = []

        products = Product.query.filter_by(

            is_active=True

        ).order_by(

            Product.display_order.asc()

        ).all()

        for product in products:

            result = self.analyze_product(

                product.id

            )

            self.save_summary(

                product.id,

                result

            )

            dashboard.append(

                {

                    "product_id": product.id,

                    "product_name": product.product_name,

                    "carry_box": result["carry_box"],

                    "carry_tl": result["carry_tl"],

                    "remaining_box": result["remaining_box"],

                    "remaining_tl": result["remaining_tl"],

                    "daily_need": result["daily_need"],

                    "projected_box": result["projected_box"],

                    "projected_percent": result["projected_percent"],

                    "risk_score": result["risk_score"],

                    "status": (

                        "Tamamlandı"

                        if result["remaining_box"] == 0

                        else "Açık"

                    )

                }

            )

        # Gerçek çalışma modunda kaydet
        if not self.overrides:

            db.session.commit()

        dashboard.sort(

            key=lambda x: (

                x["remaining_box"],

                -x["projected_percent"]

            )

        )

        return dashboard
