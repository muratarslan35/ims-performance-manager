"""Read-only quarterly entitlement report built from the monthly prime engine."""

from app.services.prime_engine import PrimeEngine


class QuarterEntitlementService:
    """Expose monthly entitlement, product carry and Q-period context together.

    It intentionally does not write a payment record.  Q review is an audit
    layer: monthly gross entitlements remain traceable and any future approved
    Q settlement rule can be added without overwriting their source values.
    """

    def __init__(self, representative_id, year, quarter):
        self.representative_id = int(representative_id)
        self.year = int(year)
        self.quarter = int(quarter)
        if self.quarter not in (1, 2, 3, 4):
            raise ValueError("Çeyrek 1 ile 4 arasında olmalıdır.")
        self.months = list(range((self.quarter - 1) * 3 + 1, (self.quarter - 1) * 3 + 4))
        self.engine = PrimeEngine(self.representative_id, self.year, self.months[-1], use_cache=False)

    @staticmethod
    def _month_label(month):
        return ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık")[month - 1]

    def _monthly_row(self, month):
        products = self.engine.calculate_monthly_products(month=month)
        summary = self.engine.summarize_products(products)
        main_prime = self.engine.calculate_main_prime(summary["total_tl_percent"]) if summary["prime_eligible"] else 0.0
        ciro_prime = 0.0 if summary["prime_eligible"] else self.engine.calculate_ciro_prime(summary["total_tl_percent"])
        gross_prime = main_prime or ciro_prime
        if main_prime:
            entitlement_type = "Ana prim"
        elif ciro_prime:
            entitlement_type = "Ciro primi"
        else:
            entitlement_type = "Hakkediş yok"
        return {
            "month": month,
            "label": self._month_label(month),
            "target_tl": summary["total_target"],
            "actual_tl": summary["total_realization"],
            "total_percent": summary["total_tl_percent"],
            "product_success": summary["product_success"],
            "main_prime": main_prime,
            "ciro_prime": ciro_prime,
            "gross_prime": gross_prime,
            "entitlement_type": entitlement_type,
            "blocked_reasons": summary["entitlement"]["blocked_reasons"],
            "has_data": bool(summary["total_target"]),
            "products": products,
        }

    def _product_carry(self):
        rows = []
        for product in self.engine.products:
            monthly = [self.engine.calculate_product(product, month=month) for month in self.months]
            target_tl = sum(item["target_tl"] for item in monthly)
            actual_tl = sum(item["actual_tl"] for item in monthly)
            target_unit = sum(item["target_unit"] for item in monthly)
            actual_unit = sum(item["actual_unit"] for item in monthly)
            percent = round(actual_tl / target_tl * 100, 2) if target_tl else 0.0
            def gap(threshold):
                required_tl = target_tl * threshold / 100
                required_unit = target_unit * threshold / 100
                return {
                    "tl": round(max(0.0, required_tl - actual_tl), 2),
                    "unit": round(max(0.0, required_unit - actual_unit), 2),
                }
            rows.append({
                "product": product.product_name,
                "is_prime_product": bool(monthly[0]["include_in_prime"]),
                "target_tl": round(target_tl, 2),
                "actual_tl": round(actual_tl, 2),
                "target_unit": round(target_unit, 2),
                "actual_unit": round(actual_unit, 2),
                "percent": percent,
                "gap_75": gap(75),
                "gap_90": gap(90),
                "gap_100": gap(100),
            })
        return rows

    def report(self):
        monthly = [self._monthly_row(month) for month in self.months]
        total_target = sum(row["target_tl"] for row in monthly)
        total_actual = sum(row["actual_tl"] for row in monthly)
        total_percent = round(total_actual / total_target * 100, 2) if total_target else 0.0
        paid = round(sum(row["gross_prime"] for row in monthly), 2)
        main_product_rows = [row for row in self._product_carry() if row["is_prime_product"]]
        return {
            "year": self.year,
            "quarter": self.quarter,
            "months": monthly,
            "products": main_product_rows,
            "summary": {
                "target_tl": round(total_target, 2),
                "actual_tl": round(total_actual, 2),
                "total_percent": total_percent,
                "gross_prime": paid,
                "main_prime_months": sum(1 for row in monthly if row["main_prime"] > 0),
                "ciro_prime_months": sum(1 for row in monthly if row["ciro_prime"] > 0),
            },
        }
