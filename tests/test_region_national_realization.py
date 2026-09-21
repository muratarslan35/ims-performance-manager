from app.services.persistent_region_snapshot_service import PersistentRegionSnapshotService


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
