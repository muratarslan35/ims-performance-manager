from app.models import (
    IMSSummary,
    Target,
    Product
)


class QuarterEngine:

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
        quarter=None,
        month=None,
        overrides=None
    ):
        self.rep_id = representative_id
        self.year = int(year)

        if quarter is None:
            if month is None:
                raise ValueError("QuarterEngine requires either quarter or month.")
            quarter = ((int(month) - 1) // 3) + 1

        self.quarter = int(quarter)
        self.months = self.QUARTERS[self.quarter]
        self.overrides = overrides or {}

    def calculate_product(

        self,

        product_id

    ):

        target_unit = 0

        target_tl = 0

        realization_unit = 0

        realization_tl = 0

        monthly = []

        for month in self.months:

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

            t_unit = 0

            t_tl = 0

            r_unit = 0

            r_tl = 0

            if target:

                t_unit = float(round(target.unit_target or 0))

                t_tl = target.tl_target

            if summary:

                r_unit = summary.unit

                r_tl = summary.tl

            override = self.overrides.get(

                product_id

            )

            if override:

                r_unit = override.get(

                    "unit",

                    r_unit

                )

                r_tl = override.get(

                    "tl",

                    r_tl

                )

            target_unit += t_unit

            target_tl += t_tl

            realization_unit += r_unit

            realization_tl += r_tl

            monthly.append(

                {

                    "month": month,

                    "target_unit": t_unit,

                    "realization_unit": r_unit,

                    "difference": (

                        r_unit -

                        t_unit

                    )

                }

            )

        percent = 0

        if target_tl > 0:

            percent = (

                realization_tl /

                target_tl

            ) * 100

        return {

            "target_unit": target_unit,

            "realization_unit": realization_unit,

            "target_tl": target_tl,

            "realization_tl": realization_tl,

            "percent": round(

                percent,

                2

            ),

            "monthly": monthly

        }

    def analyze_product(

        self,

        product_result

    ):

        carry = 0

        timeline = []

        for month in product_result["monthly"]:

            monthly_diff = month["difference"]

            carry += monthly_diff

            timeline.append(

                {

                    "month": month["month"],

                    "target": month["target_unit"],

                    "realization": month["realization_unit"],

                    "monthly_difference": monthly_diff,

                    "carry": carry

                }

            )

        closed = carry >= 0

        if closed:

            remaining = 0

            surplus = carry

        else:

            remaining = abs(

                carry

            )

            surplus = 0

        return {

            "closed": closed,

            "remaining": remaining,

            "surplus": surplus,

            "timeline": timeline

        }


    def get_product_status(

        self,

        analysis

    ):

        if analysis["closed"]:

            if analysis["surplus"] > 0:

                return "Tamamlandı"

            return "Hedef Tam"

        return "Eksik"


    def get_close_month(

        self,

        timeline

    ):

        for item in timeline:

            if item["carry"] >= 0:

                return item["month"]

        return None


    def build_dashboard(

        self,

        results

    ):

        dashboard = []

        for product_name, info in results.items():

            dashboard.append(

                {

                    "product": product_name,

                    "status": self.get_product_status(

                        info

                    ),

                    "quarter_percent": info["percent"],

                    "remaining_box": info["remaining"],

                    "surplus_box": info["surplus"],

                    "closed_month": self.get_close_month(

                        info["timeline"]

                    ),

                    "timeline": info["timeline"]

                }

            )

        return dashboard

    def calculate(

        self

    ):

        results = {}

        total_target = 0

        total_realization = 0

        total_target_tl = 0

        total_realization_tl = 0

        for product in Product.query.filter_by(

            is_active=True

        ).order_by(

            Product.display_order.asc()

        ).all():

            product_result = self.calculate_product(

                product.id

            )

            analysis = self.analyze_product(

                product_result

            )

            results[product.product_name] = {

                **product_result,

                **analysis

            }

            total_target += product_result["target_unit"]

            total_realization += product_result["realization_unit"]

            total_target_tl += product_result["target_tl"]

            total_realization_tl += product_result["realization_tl"]

        total_percent = 0

        if total_target_tl > 0:

            total_percent = round(

                (

                    total_realization_tl /

                    total_target_tl

                ) * 100,

                2

            )

        dashboard = self.build_dashboard(

            results

        )

        completed = len(

            [

                item

                for item in dashboard

                if item["status"] != "Eksik"

            ]

        )

        failed = len(

            dashboard

        ) - completed

        return {

            "year": self.year,

            "quarter": self.quarter,

            "months": self.months,

            "products": results,

            "dashboard": dashboard,

            "completed_products": completed,

            "failed_products": failed,

            "target_unit": round(

                total_target,

                2

            ),

            "realization_unit": round(

                total_realization,

                2

            ),

            "target_tl": round(

                total_target_tl,

                2

            ),

            "realization_tl": round(

                total_realization_tl,

                2

            ),

            "total_percent": total_percent,

            "simulation": (

                len(

                    self.overrides

                ) > 0

            )

        }
