from datetime import date

from app.extensions import db
from app.models import Product, Representative
from app.services.prime_engine import PrimeEngine


class SimulationService:
    def __init__(self, representative_id, year, month, overrides=None):
        self.rep_id = representative_id
        self.year = year
        self.month = month
        self.quarter = ((month - 1) // 3) + 1
        self.today = date.today()
        self.overrides = overrides or {}
        self.validate()

    def validate(self):
        representative = db.session.get(Representative, self.rep_id)
        if representative is None:
            raise Exception("Temsilci bulunamadı.")
        self.representative = representative
        if self.month < 1 or self.month > 12:
            raise Exception("Geçersiz ay.")
        if self.year < 2020:
            raise Exception("Geçersiz yıl.")

    def create_prime_engine(self, use_cache=True):
        return PrimeEngine(
            representative_id=self.rep_id,
            year=self.year,
            month=self.month,
            overrides=self.overrides,
            use_cache=use_cache,
        )

    def build_summary(self, results):
        breakdown = results["breakdown"]
        quarter = results["quarter_analysis"]
        recovery = results["recovery_analysis"]
        risk_products = len([item for item in recovery if item["status"] not in ("Tamamlandı", "Güvenli")])
        simulation_products = len([item for item in results["products"] if item["simulation"]])
        return {
            "representative_id": self.rep_id,
            "representative_name": self.representative.rep_name,
            "year": self.year,
            "month": self.month,
            "quarter": self.quarter,
            "monthly_percent": results["total_tl_percent"],
            "quarter_percent": quarter["total_percent"],
            "main_prime": breakdown["main_prime"],
            "ciro_prime": breakdown["ciro_prime"],
            "extra_prime": breakdown["extra_prime"],
            "recovery": breakdown["recovery"],
            "bonus": breakdown["bonus"],
            "penalty": breakdown["penalty"],
            "total_prime": breakdown["total"],
            "status": results["status"],
            "completed_products": quarter["completed_products"],
            "failed_products": quarter["failed_products"],
            "risk_products": risk_products,
            "simulation_products": simulation_products,
            "simulation": simulation_products > 0,
            "ai_messages": results["ai_messages"],
            "forecast_prime": results["ai_forecast"]["expected_prime"],
            "history_count": len(results.get("history", [])),
        }

    def build_result(self, results):
        return {
            "success": True,
            "summary": self.build_summary(results),
            "prime": {
                "products": results["products"],
                "product_results": results["product_results"],
                "total_target": results["total_target"],
                "total_realization": results["total_realization"],
                "total_tl_percent": results["total_tl_percent"],
                "main_prime": results["main_prime"],
                "ciro_prime": results["ciro_prime"],
                "total_prime": results["total_prime"],
                "status": results["status"],
                "message": results["message"],
            },
            "quarter": results["quarter_analysis"],
            "recovery": results["recovery_analysis"],
            "breakdown": results["breakdown"],
            "what_if": results["what_if_analysis"],
            "insights": results["insights"],
            "comparison": results["comparison_graph"],
            "trends": results["trend_graphs"],
            "forecast": results["ai_forecast"],
            "history": results.get("history", []),
            "exports": results.get("exports", {}),
            "cache": results["cache"],
        }

    def build_dashboard(self, results):
        dashboard = []
        recovery_products = {item["product_id"]: item for item in results["recovery_analysis"]}
        for item in results["quarter_analysis"]["products"]:
            recovery = recovery_products.get(item["product_id"], {})
            dashboard.append(
                {
                    "product": item["product"],
                    "product_id": item["product_id"],
                    "simulation": any(product["product_id"] == item["product_id"] and product["simulation"] for product in results["products"]),
                    "quarter_percent": item["percent"],
                    "remaining_box": recovery.get("remaining_box", 0),
                    "remaining_tl": recovery.get("remaining_tl", 0),
                    "risk_score": recovery.get("risk_score", 0),
                    "status": recovery.get("status", item["status"]),
                }
            )
        dashboard.sort(key=lambda row: (row["status"], -row["quarter_percent"]))
        return dashboard

    def build_override_report(self):
        report = []
        for product in Product.query.filter_by(is_active=True).order_by(Product.display_order.asc()).all():
            override = self.overrides.get(product.id)
            if not override:
                continue
            report.append(
                {
                    "product_id": product.id,
                    "product_name": product.product_name,
                    "unit": override.get("unit"),
                    "tl": override.get("tl"),
                    "unit_delta": override.get("unit_delta", 0),
                    "tl_delta": override.get("tl_delta", 0),
                    "slider_percent": override.get("slider_percent"),
                    "mode": override.get("mode", "delta"),
                }
            )
        return report

    def build_response(self, results):
        response = self.build_result(results)
        response["dashboard"] = self.build_dashboard(results)
        response["overrides"] = self.build_override_report()
        response["generated_at"] = self.today.isoformat()
        return response

    def run(self):
        engine = self.create_prime_engine()
        results = engine.calculate()
        results["history"] = engine.load_history()
        return self.build_response(results)

    def report(self):
        response = self.run()
        response["service"] = "SimulationService"
        response["version"] = "2.0.0"
        response["generated"] = self.today.isoformat()
        return response

    def export_pdf(self, report_type="prime_report"):
        engine = self.create_prime_engine(use_cache=False)
        results = engine.calculate()
        return engine.export_pdf(results, report_type=report_type)

    def export_excel(self):
        engine = self.create_prime_engine(use_cache=False)
        results = engine.calculate()
        return engine.export_excel(results)

    def history(self):
        return self.create_prime_engine(use_cache=False).load_history()

    @classmethod
    def health(cls):
        return {"service": "SimulationService", "status": "READY", "version": "2.0.0"}

    @classmethod
    def capabilities(cls):
        return {
            "prime": True,
            "quarter": True,
            "recovery": True,
            "dashboard": True,
            "override": True,
            "database_write": False,
            "simulation_only": True,
            "what_if": True,
            "forecast": True,
            "exports": True,
            "history": True,
            "cache": True,
        }

    @classmethod
    def example(cls):
        return {
            "representative_id": 1,
            "year": 2026,
            "month": 6,
            "overrides": {
                1: {"tl_delta": 250000, "mode": "delta"},
                2: {"tl_delta": -180000, "mode": "delta"},
                3: {"slider_percent": 125, "mode": "delta"},
            },
        }
