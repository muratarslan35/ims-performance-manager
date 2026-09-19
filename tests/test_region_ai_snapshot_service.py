from app.services.region_ai_snapshot_service import RegionAISnapshotService


def _workspace(*, brick, target=100, company=0, competitor=80, share=0):
    return {
        "snapshots": {
            "monthly": {
                "market_analysis": {
                    "brick_product_rows": [{
                        "brick": brick,
                        "product_name": "Monurol",
                        "target_unit": target,
                        "company_unit": company,
                        "competitor_unit": competitor,
                    }],
                    "brick_rows": [{
                        "brick": brick,
                        "company_unit": company,
                        "competitor_unit": competitor,
                        "market_unit": company + competitor,
                        "share_percent": share,
                    }],
                }
            }
        }
    }


def test_region_ai_snapshot_builds_four_management_signals_without_source_queries():
    report = {
        "periods": {
            "monthly": {
                "products": [
                    {"product_name": "Monurol", "realization_percent": 43.0},
                    {"product_name": "Travazol", "realization_percent": 70.0},
                ]
            }
        }
    }
    dashboard = {
        "executive_metrics": {
            "products": [
                {"product_name": "Monurol", "realization_percent": 45.0},
                {"product_name": "Travazol", "realization_percent": 68.0},
            ]
        }
    }
    current_market = {
        "rival_rows": [
            {"name": "Rakip A", "cities": [
                {"city": "DIYARBAKIR", "unit": 140},
                {"city": "MARDIN", "unit": 40},
            ]}
        ]
    }
    previous_market = {
        "rival_rows": [
            {"name": "Rakip A", "cities": [
                {"city": "DIYARBAKIR", "unit": 100},
                {"city": "MARDIN", "unit": 60},
            ]}
        ]
    }
    current = {
        1: _workspace(brick="DIYARBAKIR MERKEZ", target=120, company=0, competitor=90, share=0),
        # Same shared brick duplicated in another representative snapshot: it
        # must remain one brick, not be summed twice.
        2: _workspace(brick="DIYARBAKIR MERKEZ", target=100, company=0, competitor=90, share=0),
    }
    previous = {
        1: _workspace(brick="DIYARBAKIR MERKEZ", target=120, company=15, competitor=150, share=9),
    }

    result = RegionAISnapshotService.build(
        report=report,
        market_analysis=current_market,
        dashboard_payload=dashboard,
        previous_market_analysis=previous_market,
        current_workspaces=current,
        previous_workspaces=previous,
        year=2026,
        month=9,
    )

    assert result["source"] == "PUBLISHED_SNAPSHOTS_ONLY"
    assert result["national_underperformance"] == [{
        "product_name": "Monurol",
        "national_percent": 45.0,
        "region_percent": 43.0,
        "gap_points": 2.0,
    }]
    assert len(result["zero_exit_bricks"]) == 1
    assert result["zero_exit_bricks"][0]["brick"] == "DIYARBAKIR MERKEZ"
    assert result["zero_exit_bricks"][0]["target_unit"] == 120.0
    assert result["city_pressure"][0]["city"] == "DIYARBAKIR"
    assert result["city_pressure"][0]["delta_unit"] == 40.0
    assert result["brick_losses"][0]["brick"] == "DIYARBAKIR MERKEZ"
    assert result["brick_losses"][0]["loss_unit"] == 60.0
    assert result["previous_period"]["label"] == "08/2026"


def test_region_ai_snapshot_city_pressure_only_keeps_equal_or_growing_rival_sales():
    current = {
        "rival_rows": [{
            "name": "Rakip",
            "cities": [
                {"city": "A", "unit": 100},
                {"city": "B", "unit": 90},
                {"city": "C", "unit": 50},
            ],
        }]
    }
    previous = {
        "rival_rows": [{
            "name": "Rakip",
            "cities": [
                {"city": "A", "unit": 100},
                {"city": "B", "unit": 80},
                {"city": "C", "unit": 70},
            ],
        }]
    }

    rows = RegionAISnapshotService._city_pressure_trend(current, previous)

    assert [row["city"] for row in rows] == ["B", "A"]
    assert rows[0]["signal"] == "Artıyor"
    assert rows[1]["signal"] == "Koruyor"


def test_region_ai_snapshot_brick_loss_requires_previous_comparable_brick():
    current = {1: _workspace(brick="A", company=40, competitor=50, share=44)}
    previous = {
        1: _workspace(brick="A", company=20, competitor=80, share=20),
        2: _workspace(brick="B", company=10, competitor=100, share=9),
    }

    rows = RegionAISnapshotService._brick_competitor_losses(current, previous)

    assert len(rows) == 1
    assert rows[0]["brick"] == "A"
    assert rows[0]["loss_unit"] == 30.0
    assert rows[0]["company_unit"] == 40.0
