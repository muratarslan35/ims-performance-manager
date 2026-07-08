from datetime import date

from app.models import (
    IMSSummary,
    PrimeRule,
    Product,
    Setting,
    Target
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

        self.today = date.today()

        self.settings = self.load_settings()

        self.rules = self.load_rules()

    def load_settings(self):

        settings = {}

        for item in Setting.query.all():

            settings[item.setting_key] = item.setting_value

        return settings

    def load_rules(self):

        query = PrimeRule.query.filter_by(

            active=True

        )

        rules = []

        for rule in query.all():

            if (

                rule.valid_from

                and

                rule.valid_from > self.today

            ):

                continue

            if (

                rule.valid_to

                and

                rule.valid_to < self.today

            ):

                continue

            rules.append(rule)

        rules.sort(

            key=lambda x: x.product.display_order

            if x.product else 999

        )

        return rules

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

        target_unit = 0

        target_tl = 0

        realization_unit = 0

        realization_tl = 0

        percent = 0

        if target:

            target_unit = target.unit_target

            target_tl = target.tl_target

        if summary:

            realization_unit = summary.unit

            realization_tl = summary.tl

        if target_tl > 0:

            percent = (

                realization_tl /

                target_tl

            ) * 100

        return {

            "target_unit": target_unit,

            "target_tl": target_tl,

            "realization_unit": realization_unit,

            "realization_tl": realization_tl,

            "percent": round(

                percent,

                2

            )

        }

    def get_setting(

        self,

        key,

        default=0

    ):

        try:

            return float(

                self.settings.get(

                    key,

                    default

                )

            )

        except Exception:

            return default

    def calculate_main_prime(

        self,

        total_percent

    ):

        minimum = self.get_setting(

            "MIN_PRIME_PERCENT",

            100

        )

        maximum = self.get_setting(

            "MAX_PRIME_PERCENT",

            140

        )

        base = self.get_setting(

            "MAIN_PRIME",

            50000

        )

        step = self.get_setting(

            "PRIME_STEP",

            5

        )

        step_amount = self.get_setting(

            "STEP_AMOUNT",

            2500

        )

        if total_percent < minimum:

            return 0

        total_percent = min(

            total_percent,

            maximum

        )

        level = int(

            (

                total_percent -

                minimum

            ) // step

        )

        return base + (

            level *

            step_amount

        )

    def calculate_ciro_prime(

        self,

        total_percent,

        product_success

    ):

        allow = int(

            self.get_setting(

                "ALLOW_CIRO_WITHOUT_PRODUCT",

                1

            )

        )

        minimum = self.get_setting(

            "TOTAL_PERCENT_REQUIRED",

            100

        )

        if total_percent < minimum:

            return 0

        if product_success:

            return self.get_setting(

                "CIRO_PRIME",

                20000

            )

        if allow == 1:

            return self.get_setting(

                "CIRO_PRIME",

                20000

            )

        return 0


    def analyze_rules(

        self,

        product_results

    ):

        success = True

        passed = []

        failed = []

        for rule in self.rules:

            product = rule.product

            if product is None:

                continue

            info = product_results.get(

                product.id

            )

            if info is None:

                success = False

                failed.append({

                    "product": product.product_name,

                    "required": rule.required_percent,

                    "actual": 0

                })

                continue

            if info["percent"] >= rule.required_percent:

                passed.append({

                    "product": product.product_name,

                    "required": rule.required_percent,

                    "actual": info["percent"]

                })

            else:

                success = False

                failed.append({

                    "product": product.product_name,

                    "required": rule.required_percent,

                    "actual": info["percent"]

                })

        return {

            "success": success,

            "passed": passed,

            "failed": failed

        }


    def finalize(

        self,

        result

    ):

        result["main_prime"] = 0

        result["ciro_prime"] = 0

        result["total_prime"] = 0

        result["status"] = "Başarısız"

        if result["product_success"]:

            result["main_prime"] = self.calculate_main_prime(

                result["total_tl_percent"]

            )

        result["ciro_prime"] = self.calculate_ciro_prime(

            result["total_tl_percent"],

            result["product_success"]

        )

        result["total_prime"] = (

            result["main_prime"]

            +

            result["ciro_prime"]

        )

        if result["main_prime"] > 0:

            result["status"] = "Ana Prim"

        elif result["ciro_prime"] > 0:

            result["status"] = "Ciro Primi"

        if result["total_prime"] > 0:

            result["success"] = True

        return result

    def calculate(

        self

    ):

        result = {

            "products": {},

            "product_results": {},

            "passed_products": [],

            "failed_products": [],

            "total_target": 0,

            "total_realization": 0,

            "total_tl_percent": 0,

            "main_prime": 0,

            "ciro_prime": 0,

            "total_prime": 0,

            "product_success": False,

            "success": False,

            "status": "",

            "message": ""

        }

        total_target = 0

        total_realization = 0

        for rule in self.rules:

            product = rule.product

            if product is None:

                continue

            info = self.calculate_product(

                product.id

            )

            result["products"][

                product.product_name

            ] = info

            result["product_results"][

                product.id

            ] = info

            if rule.include_in_total_tl:

                total_target += info["target_tl"]

                total_realization += info["realization_tl"]

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

        analyze = self.analyze_rules(

            result["product_results"]

        )

        result["product_success"] = analyze["success"]

        result["passed_products"] = analyze["passed"]

        result["failed_products"] = analyze["failed"]

        result["rule_summary"] = {

            "rule_count": len(

                self.rules

            ),

            "passed_count": len(

                analyze["passed"]

            ),

            "failed_count": len(

                analyze["failed"]

            ),

            "required_total_percent": self.get_setting(

                "TOTAL_PERCENT_REQUIRED",

                100

            )

        }

        reasons = []

        if len(

            analyze["failed"]

        ) > 0:

            for item in analyze["failed"]:

                reasons.append(

                    f'{item["product"]} (%{item["actual"]:.1f} / %{item["required"]})'

                )

        if (

            result["total_tl_percent"]

            <

            self.get_setting(

                "TOTAL_PERCENT_REQUIRED",

                100

            )

        ):

            reasons.append(

                f'Toplam TL %{result["total_tl_percent"]:.2f}'

            )

        if len(

            reasons

        ) == 0:

            result["message"] = (

                "Tüm prim koşulları sağlandı."

            )

        else:

            result["message"] = " | ".join(

                reasons

            )

        return self.finalize(

            result

        )
