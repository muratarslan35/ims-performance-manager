from datetime import date

from app.prime_engine import PrimeEngine
from app.quarter_engine import QuarterEngine
from app.recovery_engine import RecoveryEngine

from app.models import (
    Product,
    Representative
)


class SimulationService:

    def __init__(

        self,

        representative_id,

        year,

        month,

        overrides=None

    ):

        self.rep_id = representative_id

        self.year = year

        self.month = month

        self.quarter = (

            (month - 1) // 3

        ) + 1

        self.today = date.today()

        self.overrides = overrides or {}

        self.validate()

        self.prepare_overrides()


    def validate(

        self

    ):

        representative = Representative.query.get(

            self.rep_id

        )

        if representative is None:

            raise Exception(

                "Temsilci bulunamadı."

            )

        self.representative = representative

        if self.month < 1 or self.month > 12:

            raise Exception(

                "Geçersiz ay."

            )

        if self.year < 2020:

            raise Exception(

                "Geçersiz yıl."

            )


    def prepare_overrides(

        self

    ):

        prepared = {}

        for product in Product.query.filter_by(

            is_active=True

        ).all():

            prepared[

                product.id

            ] = {

                "unit": 0,

                "tl": 0,

                "simulation": False

            }

        for product_id, values in self.overrides.items():

            if product_id not in prepared:

                continue

            prepared[

                product_id

            ]["unit"] = float(

                values.get(

                    "unit",

                    0

                )

            )

            prepared[

                product_id

            ]["tl"] = float(

                values.get(

                    "tl",

                    0

                )

            )

            prepared[

                product_id

            ]["simulation"] = True

        self.overrides = prepared


    def create_prime_engine(

        self

    ):

        return PrimeEngine(

            representative_id=self.rep_id,

            year=self.year,

            month=self.month,

            overrides=self.overrides

        )


    def create_quarter_engine(

        self

    ):

        return QuarterEngine(

            representative_id=self.rep_id,

            year=self.year,

            quarter=self.quarter,

            overrides=self.overrides

        )


    def create_recovery_engine(

        self

        ):

        return RecoveryEngine(

            representative_id=self.rep_id,

            year=self.year,

            quarter=self.quarter,

            overrides=self.overrides

        )

    def calculate_prime(

        self

        ):

        engine = self.create_prime_engine()

        return engine.calculate()


    def calculate_quarter(

        self

        ):

        engine = self.create_quarter_engine()

        return engine.calculate()


    def calculate_recovery(

        self

        ):

        engine = self.create_recovery_engine()

        return engine.run()


    def calculate_all(

        self

        ):

        prime = self.calculate_prime()

        quarter = self.calculate_quarter()

        recovery = self.calculate_recovery()

        return {

            "prime": prime,

            "quarter": quarter,

            "recovery": recovery

        }


    def build_summary(

        self,

        results

        ):

        prime = results["prime"]

        quarter = results["quarter"]

        recovery = results["recovery"]

        risk_products = len(

            [

                item

                for item in recovery

                if item["status"] != "Tamamlandı"

            ]

        )

        simulation_products = len(

            [

                item

                for item

                in self.overrides.values()

                if item["simulation"]

            ]

        )

        return {

            "representative_id":

                self.rep_id,

            "year":

                self.year,

            "month":

                self.month,

            "quarter":

                self.quarter,

            "monthly_percent":

                prime["total_tl_percent"],

            "quarter_percent":

                quarter["total_percent"],

            "main_prime":

                prime["main_prime"],

            "ciro_prime":

                prime["ciro_prime"],

            "total_prime":

                prime["total_prime"],

            "status":

                prime["status"],

            "completed_products":

                quarter["completed_products"],

            "failed_products":

                quarter["failed_products"],

            "risk_products":

                risk_products,

            "simulation_products":

                simulation_products,

            "simulation":

                simulation_products > 0

        }


    def build_result(

        self,

        results

        ):

        return {

            "success": True,

            "summary": self.build_summary(

                results

            ),

            "prime": results["prime"],

            "quarter": results["quarter"],

            "recovery": results["recovery"]

        }
    def build_dashboard(

        self,

        results

        ):

        dashboard = []

        quarter_products = results[

            "quarter"

        ][

            "products"

        ]

        recovery_products = {

            item["product_name"]: item

            for item

            in results["recovery"]

        }

        for product_name, quarter in quarter_products.items():

            recovery = recovery_products.get(

                product_name,

                {}

            )

            dashboard.append(

                {

                    "product": product_name,

                    "simulation":

                        self.overrides.get(

                            quarter.get(

                                "product_id",

                                0

                            ),

                            {}

                        ).get(

                            "simulation",

                            False

                        ),

                    "quarter_percent":

                        quarter.get(

                            "percent",

                            0

                        ),

                    "remaining_box":

                        recovery.get(

                            "remaining_box",

                            0

                        ),

                    "remaining_tl":

                        recovery.get(

                            "remaining_tl",

                            0

                        ),

                    "risk_score":

                        recovery.get(

                            "risk_score",

                            0

                        ),

                    "status":

                        recovery.get(

                            "status",

                            "-"

                        )

                }

            )

        dashboard.sort(

            key=lambda x:

            (

                x["status"],

                -x["quarter_percent"]

            )

        )

        return dashboard


    def build_override_report(

        self

        ):

        report = []

        for product in Product.query.filter_by(

            is_active=True

        ).order_by(

            Product.display_order.asc()

        ).all():

            override = self.overrides.get(

                product.id

            )

            if not override:

                continue

            if not override.get(

                "simulation"

        ):

                continue

            report.append(

                {

                    "product_id":

                        product.id,

                    "product_name":

                        product.product_name,

                    "unit":

                        override["unit"],

                    "tl":

                        override["tl"]

                }

            )

        return report


    def build_response(

        self,

        results

        ):

        response = self.build_result(

            results

        )

        response[

            "dashboard"

        ] = self.build_dashboard(

            results

        )

        response[

            "overrides"

        ] = self.build_override_report()

        response[

            "generated_at"

        ] = self.today.isoformat()

        return response

    def run(

        self

        ):

        results = self.calculate_all()

        return self.build_response(

            results

        )


    def report(

        self

        ):

        response = self.run()

        response[

            "service"

        ] = "SimulationService"

        response[

            "version"

        ] = "1.0.0"

        response[

            "generated"

        ] = self.today.isoformat()

        return response


    @classmethod
    def health(

        cls

        ):

        return {

            "service":

                "SimulationService",

            "status":

                "READY",

            "version":

                "1.0.0"

        }


    @classmethod
    def capabilities(

        cls

        ):

        return {

            "prime":

                True,

            "quarter":

                True,

            "recovery":

                True,

            "dashboard":

                True,

            "override":

                True,

            "database_write":

                False,

            "simulation_only":

                True

        }


    @classmethod
    def example(

        cls

        ):

        return {

            "representative_id": 1,

            "year": 2026,

            "month": 6,

            "overrides": {

                1: {

                    "unit": 2500,

                    "tl": 450000,

                    "simulation": True

                },

                2: {

                    "unit": 850,

                    "tl": 120000,

                    "simulation": True

                }

            }

        }
