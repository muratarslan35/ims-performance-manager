from app.models import (
    Product,
    Target,
    Setting,
    IMSSummary
)


class PrimeEngine:

    def __init__(
        self,
        representative_id,
        year,
        month
    ):

        self.rep_id = representative_id
        self.year = year
        self.month = month

        self.settings = self.load_settings()

    def load_settings(self):

        data = {}

        settings = Setting.query.all()

        for item in settings:

            data[item.setting_key] = item.setting_value

        return data

    def calculate_product(

        self,

        product_id

    ):

        target = Target.query.filter_by(

            representative_id=self.rep_id,

            product_id=product_id,

            year=self.year,

            month=self.month

        ).first()

        summary = IMSSummary.query.filter_by(

            representative_id=self.rep_id,

            product_id=product_id,

            year=self.year,

            month=self.month

        ).first()

        target_tl = 0
        realization_tl = 0
        percent = 0

        if target:

            target_tl = target.tl_target

        if summary:

            realization_tl = summary.tl

        if target_tl > 0:

            percent = (

                realization_tl /

                target_tl

            ) * 100

        return {

            "target": target_tl,

            "realization": realization_tl,

            "percent": round(

                percent,

                2

            )

        }

    def calculate_main_prime(

        self,

        total_percent

    ):

        minimum = float(

            self.settings.get(

                "MIN_PRIME_PERCENT",

                100

            )

        )

        maximum = float(

            self.settings.get(

                "MAX_PRIME_PERCENT",

                140

            )

        )

        base_prime = float(

            self.settings.get(

                "MAIN_PRIME",

                50000

            )

        )

        step = float(

            self.settings.get(

                "PRIME_STEP",

                5

            )

        )

        step_amount = float(

            self.settings.get(

                "STEP_AMOUNT",

                2500

            )

        )

        if total_percent < minimum:

            return 0

        if total_percent > maximum:

            total_percent = maximum

        extra = total_percent - minimum

        level = int(

            extra // step

        )

        return base_prime + (

            level *

            step_amount

        )

    def calculate_ciro_prime(

        self,

        total_percent

    ):

        if total_percent >= 100:

            return float(

                self.settings.get(

                    "CIRO_PRIME",

                    20000

                )

            )

        return 0

    def finalize(

        self,

        result

    ):

        if not result["success"]:

            result["main_prime"] = 0

            result["ciro_prime"] = 0

            result["total_prime"] = 0

            result["status"] = "Başarısız"

            return result

        result["main_prime"] = self.calculate_main_prime(

            result["total_tl_percent"]

        )

        result["ciro_prime"] = self.calculate_ciro_prime(

            result["total_tl_percent"]

        )

        result["total_prime"] = (

            result["main_prime"]

            +

            result["ciro_prime"]

        )

        result["status"] = "Hak Kazandı"

        return result

    def calculate(

        self

    ):

        result = {

            "products": {},

            "total_target": 0,

            "total_realization": 0,

            "total_tl_percent": 0,

            "main_prime": 0,

            "ciro_prime": 0,

            "total_prime": 0,

            "success": False,

            "status": ""

        }

        products = Product.query.filter_by(

            is_prime_product=True,

            is_active=True

        ).order_by(

            Product.display_order.asc()

        ).all()

        success90 = 0

        success75 = 0

        total_target = 0

        total_realization = 0

        for product in products:

            info = self.calculate_product(

                product.id

            )

            result["products"][

                product.product_name

            ] = info

            total_target += info["target"]

            total_realization += info["realization"]

            if info["percent"] >= 90:

                success90 += 1

            elif info["percent"] >= 75:

                success75 += 1

        result["total_target"] = round(

            total_target,

            2

        )

        result["total_realization"] = round(

            total_realization,

            2

        )

        if total_target > 0:

            result["total_tl_percent"] = round(

                (

                    total_realization /

                    total_target

                ) * 100,

                2

            )

        result["success"] = (

            success90 >= 3

            and

            success75 >= 1

            and

            result["total_tl_percent"] >= float(

                self.settings.get(

                    "TARGET_100",

                    100

                )

            )

        )

        result["rule_summary"] = {

            "required_90": 3,

            "current_90": success90,

            "required_75": 1,

            "current_75": success75,

            "total_target": round(

                total_target,

                2

            ),

            "total_realization": round(

                total_realization,

                2

            )

        }

        if result["success"]:

            result["message"] = (

                "Prim şartları sağlandı."

            )

        else:

            reasons = []

            if success90 < 3:

                reasons.append(

                    f"%90 üzeri ürün sayısı yetersiz ({success90}/3)"

                )

            if success75 < 1:

                reasons.append(

                    f"%75 üzeri ürün sayısı yetersiz ({success75}/1)"

                )

            if result["total_tl_percent"] < float(

                self.settings.get(

                    "TARGET_100",

                    100

                )

            ):

                reasons.append(

                    "Toplam TL realizasyonu %100'ün altında"

                )

            result["message"] = " | ".join(

                reasons

            )

        return self.finalize(

            result

        )
