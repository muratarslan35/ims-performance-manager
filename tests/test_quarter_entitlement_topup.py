from app.services.quarter_entitlement_service import QuarterEntitlementService


class FakeEngine:
    def get_setting(self, key, default):
        return {"MAIN_PRIME": 50000.0, "TOTAL_PERCENT_REQUIRED": 100.0}.get(key, default)

    def evaluate_monthly_entitlement(self, products):
        over_90 = sum(1 for row in products if row["percent"] >= 90)
        success = len(products) == 4 and all(row["percent"] >= 75 for row in products) and over_90 >= 3
        return {"product_success": success}


def _service(monthly, products):
    service = QuarterEntitlementService.__new__(QuarterEntitlementService)
    service.year = 2026
    service.quarter = 1
    service.months = [1, 2, 3]
    service.engine = FakeEngine()
    service._monthly_row = lambda month: dict(monthly[month - 1])
    service._product_carry = lambda: [dict(row) for row in products]
    return service


def _month(month, target, actual, gross):
    return {
        "month": month,
        "label": ("Ocak", "Şubat", "Mart")[month - 1],
        "target_tl": target,
        "actual_tl": actual,
        "total_percent": round(actual / target * 100, 2),
        "product_success": gross > 0,
        "main_prime": gross,
        "ciro_prime": 0.0,
        "gross_prime": gross,
        "entitlement_type": "Ana prim" if gross else "Hakkediş yok",
        "blocked_reasons": [],
        "has_data": True,
        "products": [],
    }


def _q_products(percentages=(111, 92, 85, 131)):
    return [
        {"product": name, "percent": percent, "is_prime_product": True}
        for name, percent in zip(("Travazol", "Monurol", "Mixovul", "Acnemix"), percentages)
    ]


def test_q_closing_pays_only_remaining_base_entitlement():
    report = _service(
        [
            _month(1, 1_592_040, 1_981_806, 60_000),
            _month(2, 1_565_769, 1_630_473, 50_000),
            _month(3, 1_589_924, 1_568_134, 0),
        ],
        _q_products(),
    ).report()

    assert report["summary"]["q_entitlement_cap"] == 150_000
    assert report["summary"]["monthly_paid"] == 110_000
    assert report["summary"]["q_topup"] == 40_000
    assert report["summary"]["gross_prime"] == 150_000
    assert report["months"][2]["gross_prime"] == 40_000
    assert report["months"][2]["entitlement_type"] == "Q telafi hakkedişi"


def test_q_topup_never_reapplies_steps_or_creates_negative_payment():
    assert QuarterEntitlementService._q_topup(
        160_000, 150_000, complete=True, total_success=True, product_success=True
    ) == 0


def test_q_topup_requires_complete_q_total_and_product_conditions():
    assert QuarterEntitlementService._q_topup(
        110_000, 150_000, complete=False, total_success=True, product_success=True
    ) == 0
    assert QuarterEntitlementService._q_topup(
        110_000, 150_000, complete=True, total_success=False, product_success=True
    ) == 0
    assert QuarterEntitlementService._q_topup(
        110_000, 150_000, complete=True, total_success=True, product_success=False
    ) == 0
