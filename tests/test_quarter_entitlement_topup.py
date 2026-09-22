from contextlib import nullcontext
from types import SimpleNamespace

import app.services.quarter_entitlement_service as quarter_module
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

def test_q_summary_exposes_non_negative_remaining_tl_gap():
    report = _service(
        [
            _month(1, 1_000_000, 700_000, 0),
            _month(2, 1_000_000, 900_000, 0),
            _month(3, 1_000_000, 800_000, 0),
        ],
        _q_products((80, 80, 80, 80)),
    ).report()
    assert report["summary"]["target_tl"] == 3_000_000
    assert report["summary"]["actual_tl"] == 2_400_000
    assert report["summary"]["remaining_tl"] == 600_000

    over_target = _service(
        [
            _month(1, 1_000_000, 1_100_000, 0),
            _month(2, 1_000_000, 1_050_000, 0),
            _month(3, 1_000_000, 1_020_000, 0),
        ],
        _q_products(),
    ).report()
    assert over_target["summary"]["remaining_tl"] == 0



def test_quota_exit_is_available_for_every_quarter(monkeypatch):
    monkeypatch.setattr(
        quarter_module,
        "PrimeEngine",
        lambda *args, **kwargs: FakeEngine(),
    )
    monkeypatch.setattr(
        quarter_module.ProductionResultService,
        "quota_product_months",
        lambda periods: {},
    )

    expected = {
        1: [1, 2, 3],
        2: [4, 5, 6],
        3: [7, 8, 9],
        4: [10, 11, 12],
    }
    for quarter, months in expected.items():
        service = QuarterEntitlementService(97, 2026, quarter)
        assert service.months == months


def test_quota_exit_lifts_only_selected_snapshot_product_to_minimum_100(monkeypatch):
    service = QuarterEntitlementService.__new__(QuarterEntitlementService)
    service.representative_id = 97
    service.year = 2026
    service.quarter = 3
    service.months = [7, 8, 9]
    service.quota_exit_by_month = {8: 11}
    service._official_quota = {}
    service._snapshot_rows = {}

    product = SimpleNamespace(
        id=11,
        product_name="Fentivag",
        include_total_tl=True,
        is_prime_product=True,
        required_percent=90,
    )
    rule = SimpleNamespace(
        include_in_total_tl=True,
        include_in_prime=True,
        required_percent=90,
    )
    service.engine = SimpleNamespace(
        products=[product],
        get_prime_rule=lambda _product: rule,
    )

    workspace = {
        "snapshots": {
            "monthly": {
                "months": [[2026, 8]],
                "products": [{
                    "product": {"id": 11, "product_name": "Fentivag"},
                    "target_tl": 100_000,
                    "actual_tl": 80_000,
                    "target_unit": 100,
                    "actual_unit": 80,
                }],
            }
        }
    }
    monkeypatch.setattr(
        quarter_module.PersistentRepresentativeSnapshotService,
        "get_active",
        lambda representative_id, year, month: workspace,
    )

    rows, quota, available = service._snapshot_products(8)

    assert available is True
    assert quota["selected_id"] == 11
    assert rows[0]["actual_tl"] == 100_000
    assert rows[0]["actual_unit"] == 100
    assert rows[0]["percent"] == 100
    assert rows[0]["quota_uplift_tl"] == 20_000


def test_missing_historical_snapshot_uses_bounded_authoritative_history(monkeypatch):
    service = QuarterEntitlementService.__new__(QuarterEntitlementService)
    service.representative_id = 97
    service.year = 2026
    service.quarter = 3
    service.months = [7, 8, 9]
    service.quota_exit_by_month = {8: 11}
    service._official_quota = {}
    service._snapshot_rows = {}

    product = SimpleNamespace(
        id=11,
        product_name="Fentivag",
        include_total_tl=True,
        is_prime_product=True,
        required_percent=90,
    )
    rule = SimpleNamespace(
        include_in_total_tl=True,
        include_in_prime=True,
        required_percent=90,
    )
    service.engine = SimpleNamespace(
        products=[product],
        get_prime_rule=lambda _product: rule,
        _calc_cache={},
        calculate_monthly_products=lambda month: [{
            "product_id": 11,
            "product_name": "Fentivag",
            "target_tl": 100_000,
            "actual_tl": 80_000,
            "target_unit": 100,
            "actual_unit": 80,
            "percent": 80,
            "gap_tl": 20_000,
            "required_percent": 90,
            "include_in_total_tl": True,
            "include_in_prime": True,
        }],
    )

    monkeypatch.setattr(
        quarter_module.PersistentRepresentativeSnapshotService,
        "get_active",
        lambda representative_id, year, month: None,
    )
    monkeypatch.setattr(
        quarter_module.ProductionResultService,
        "effective_products",
        lambda year, month, representative_id: {11: {"source": "PRODUCTION_2"}},
    )
    monkeypatch.setattr(
        quarter_module.ProductionResultService,
        "use_effective_batch",
        lambda year, month, representative_id, rows: nullcontext(rows),
    )

    rows, quota, available = service._snapshot_products(8)

    assert available is True
    assert quota["source"] == "AUTHORITATIVE_HISTORY"
    assert quota["selected_id"] == 11
    assert rows[0]["actual_tl"] == 100_000
    assert rows[0]["percent"] == 100
    assert rows[0]["quota_uplift_tl"] == 20_000


def test_all_quarters_can_resolve_historical_months_without_persisted_month_snapshot(monkeypatch):
    service = QuarterEntitlementService.__new__(QuarterEntitlementService)
    service.representative_id = 97
    service.year = 2026
    service.quota_exit_by_month = {}
    service._official_quota = {}
    service._snapshot_rows = {}
    service.engine = SimpleNamespace(products=[])

    monkeypatch.setattr(
        quarter_module.PersistentRepresentativeSnapshotService,
        "get_active",
        lambda representative_id, year, month: None,
    )
    service._historical_products = lambda month: [{
        "product_id": month,
        "product_name": f"Ürün {month}",
        "target_tl": 100,
        "actual_tl": 90,
        "target_unit": 10,
        "actual_unit": 9,
        "percent": 90,
        "gap_tl": 10,
        "required_percent": 0,
        "include_in_total_tl": True,
        "include_in_prime": False,
        "quota_exit": False,
        "quota_uplift_tl": 0,
        "quota_uplift_unit": 0,
    }]

    for quarter, months in {
        1: [1, 2, 3],
        2: [4, 5, 6],
        3: [7, 8, 9],
        4: [10, 11, 12],
    }.items():
        service.quarter = quarter
        service.months = months
        for month in months:
            rows, quota, available = service._snapshot_products(month)
            assert available is True
            assert rows[0]["month"] == month
            assert quota["source"] == "AUTHORITATIVE_HISTORY"
