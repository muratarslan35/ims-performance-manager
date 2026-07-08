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
