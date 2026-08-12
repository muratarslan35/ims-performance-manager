from types import SimpleNamespace

from app.services.dashboard_service import DashboardService


def row(**values):
    return SimpleNamespace(**values)


def test_regional_competition_uses_weighted_national_benchmark_and_balanced_signals():
    products = [row(product_name="Bilim Ürün")]
    competition = [
        row(territory="101 İSTANBUL", product_group="TEST GRUP", product_name="Bilim Ürün", sales_tl=100),
        row(territory="101 İSTANBUL", product_group="TEST GRUP", product_name="Rakip A", sales_tl=300),
        row(territory="201 KADIKÖY", product_group="TEST GRUP", product_name="Bilim Ürün", sales_tl=200),
        row(territory="201 KADIKÖY", product_group="TEST GRUP", product_name="Rakip B", sales_tl=200),
        row(territory="GENEL TOPLAM", product_group="TEST GRUP", product_name="", sales_tl=800),
    ]

    result = DashboardService._regional_competition(competition, products)
    rows = {item["territory"]: item for item in result["table"]}

    assert rows["101 İSTANBUL"]["company_tl"] == 100
    assert rows["101 İSTANBUL"]["competitor_tl"] == 300
    assert rows["101 İSTANBUL"]["market_tl"] == 400
    assert rows["101 İSTANBUL"]["share_percent"] == 25
    assert rows["101 İSTANBUL"]["national_share_percent"] == 37.5
    assert rows["101 İSTANBUL"]["difference_pp"] == -12.5
    assert rows["201 KADIKÖY"]["difference_pp"] == 12.5
    assert {item["signal_type"] for item in result["signals"]} == {"risk", "strong"}
    assert result["validation"] == {
        "is_valid": True,
        "valid_rows": 2,
        "invalid_rows": 0,
        "formula": "company_tl / market_tl * 100",
        "benchmark": "weighted national product-group share",
    }


def test_regional_competition_summary_matches_detail_totals():
    products = [row(product_name="Bilim Ürün")]
    competition = [
        row(territory="101", product_group="A", product_name="Bilim Ürün", sales_tl=20),
        row(territory="101", product_group="A", product_name="Rakip", sales_tl=80),
        row(territory="201", product_group="A", product_name="Bilim Ürün", sales_tl=40),
        row(territory="201", product_group="A", product_name="Rakip", sales_tl=60),
    ]

    result = DashboardService._regional_competition(competition, products)

    assert result["summary"]["territory_count"] == 2
    assert result["summary"]["product_group_count"] == 1
    assert result["summary"]["row_count"] == 2
    assert result["summary"]["company_tl"] == sum(item["company_tl"] for item in result["table"])
    assert result["summary"]["market_tl"] == sum(item["market_tl"] for item in result["table"])
    assert result["summary"]["weighted_share_percent"] == 30
