from app.services.persistent_region_snapshot_service import PersistentRegionSnapshotService
from pathlib import Path


def test_national_product_realization_is_embedded_from_dashboard_snapshot_only():
    report = {
        "periods": {
            "monthly": {
                "products": [
                    {"product_id": 7, "product_name": "Travazol", "realization_percent": 42},
                    {"product_id": 8, "product_name": "Monurol", "realization_percent": 55},
                ]
            }
        }
    }
    dashboard = {
        "executive_metrics": {
            "products": [
                {"product_id": 7, "product_name": "Travazol", "realization_percent": 61.4},
                {"product_id": 8, "product_name": "Monurol", "realization_percent": 49.6},
            ]
        }
    }

    result = PersistentRegionSnapshotService._embed_national_product_realizations(
        report, dashboard
    )

    assert [
        row["national_realization_percent"]
        for row in result["periods"]["monthly"]["products"]
    ] == [61.4, 49.6]


def test_region_national_comparison_ui_is_scoped_to_region_table():
    template = Path("app/templates/region_performance_quarter.html").read_text(
        encoding="utf-8"
    )

    assert '<span>BÖLGE</span><span>REALİZASYONU</span>' in template
    assert '<span>NATIONAL</span><span>REALİZASYONU</span>' in template
    assert "national-comparison-pill" in template
    assert "item.realization_percent >= item.national_realization_percent" in template
    assert ".quarter-period-panel .national-comparison-pill.region-ahead" in template
    assert ".quarter-period-panel .national-comparison-pill.region-behind" in template
    assert "product-comparison-table" in template
    assert '<col style="width:13%"><col style="width:13%">' in template
    assert "td:nth-child(6),.quarter-period-panel .product-comparison-table td:nth-child(7){text-align:center!important}" in template
