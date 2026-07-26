from copy import deepcopy

from app.models import (
    Product,
    Target,
    IMSSummary
)

from app.prime_engine import PrimeEngine
from app.recovery_engine import RecoveryEngine
from app.quarter_engine import QuarterEngine


class PrimeSimulator:

    def __init__(

        self,

        representative_id,

        year,

        month

    ):

        self.rep_id = representative_id

        self.year = year

        self.month = month

        self.quarter = self.get_quarter()

    def get_quarter(

        self

    ):

        if self.month <= 3:

            return 1

        if self.month <= 6:

            return 2

        if self.month <= 9:

            return 3

        return 4

    def load_current_state(

        self

    ):

        prime = PrimeEngine(

            self.rep_id,

            self.year,

            self.month

        ).calculate()

        recovery = RecoveryEngine(

            self.rep_id,

            self.year,

            self.quarter

        ).run()

        quarter = QuarterEngine(

            self.rep_id,

            self.year,

            self.quarter

        ).calculate()

        return {

            "prime": prime,

            "recovery": recovery,

            "quarter": quarter

        }

    def get_summary(

        self,

        product_id

    ):

        return IMSSummary.query.filter_by(

            representative_id=self.rep_id,

            product_id=product_id,

            year=self.year,

            month=self.month

        ).first()

    def simulate(

        self,

        product_id,

        additional_box=0,

        additional_tl=0

    ):

        current = self.load_current_state()

        summary = self.get_summary(

            product_id

        )

        if summary is None:

            raise ValueError(

                "IMS özeti bulunamadı."

            )

        simulated_unit = (

            summary.unit +

            additional_box

        )

        simulated_tl = (

            summary.tl +

            additional_tl

        )

        target = Target.query.filter_by(

            representative_id=self.rep_id,

            product_id=product_id,

            year=self.year,

            month=self.month

        ).first()

        target_unit = 0
        target_tl = 0

        if target:

            target_unit = target.unit_target
            target_tl = target.tl_target

        simulated_percent = 0

        if target_tl > 0:

            simulated_percent = round(

                (

                    simulated_tl /

                    target_tl

                ) * 100,

                2

            )

        recovery = RecoveryEngine(

            self.rep_id,

            self.year,

            self.quarter

        ).simulate(

            product_id,

            additional_box,

            additional_tl

        )

        difference_box = (

            simulated_unit -

            summary.unit

        )

        difference_tl = (

            simulated_tl -

            summary.tl

        )

        return {

            "product_id": product_id,

            "current_box": summary.unit,

            "simulated_box": simulated_unit,

            "current_tl": summary.tl,

            "simulated_tl": simulated_tl,

            "difference_box": difference_box,

            "difference_tl": difference_tl,

            "target_box": target_unit,

            "target_tl": target_tl,

            "simulated_percent": simulated_percent,

            "recovery": recovery,

            "current_state": current

        }

    def simulate_multiple(

        self,

        scenarios

    ):

        current = self.load_current_state()

        simulations = []

        total_added_box = 0
        total_added_tl = 0

        for item in scenarios:

            product_id = item["product_id"]

            add_box = item.get(

                "additional_box",

                0

            )

            add_tl = item.get(

                "additional_tl",

                0

            )

            simulation = self.simulate(

                product_id,

                add_box,

                add_tl

            )

            simulations.append(

                simulation

            )

            total_added_box += add_box

            total_added_tl += add_tl

        recovery = RecoveryEngine(

            self.rep_id,

            self.year,

            self.quarter

        ).run()

        prime = PrimeEngine(

            self.rep_id,

            self.year,

            self.month

        ).calculate()

        completed = 0

        risky = 0

        critical = 0

        for item in recovery:

            status = item["status"]

            if status == "Tamamlandı":

                completed += 1

            elif item["risk_score"] < 40:

                critical += 1

            else:

                risky += 1

        return {

            "simulations": simulations,

            "summary": {

                "added_box": total_added_box,

                "added_tl": total_added_tl,

                "completed_products": completed,

                "risky_products": risky,

                "critical_products": critical,

                "current_prime": prime["total_prime"],

                "current_percent": prime["total_tl_percent"],

                "current_status": prime["status"]

            },

            "current_state": current

        }


    def recommendation(

        self,

        scenarios

    ):

        result = self.simulate_multiple(

            scenarios

        )

        recommendations = []

        for item in result["simulations"]:

            recovery = item["recovery"]

            if recovery["remaining_box"] == 0:

                recommendations.append(

                    {

                        "product_id": item["product_id"],

                        "message":

                        "Q hedefi kapanıyor."

                    }

                )

            else:

                recommendations.append(

                    {

                        "product_id": item["product_id"],

                        "message":

                        f"{recovery['remaining_box']} kutu daha gerekiyor."

                    }

                )

        result["recommendations"] = recommendations

        return result
