from app.services.region_ai_snapshot_service import RegionAISnapshotService


def _workspace(*, brick, product="Monurol", target=100, company=0, competitor=80, share=0):
    return {
        "snapshots": {
            "monthly": {
                "market_analysis": {
                    "brick_product_rows": [{
                        "brick": brick,
                        "product_name": product,
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
                {"product_name": "Monurol", "realization_percent": 45.0, "unit_actual": 500},
                {"product_name": "Travazol", "realization_percent": 68.0, "unit_actual": 400},
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
    assert result["brick_losses"][0]["product_name"] == "Monurol"
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
    assert rows[0]["product_name"] == "Monurol"
    assert rows[0]["loss_unit"] == 30.0
    assert rows[0]["company_unit"] == 40.0

def test_zero_exit_excludes_product_with_no_national_sales_but_keeps_active_product():
    workspaces = {
        1: _workspace(
            brick="SANLIURFA MERKEZ", product="Fentivag",
            target=1000, company=0, competitor=900,
        ),
        2: _workspace(
            brick="DIYARBAKIR YENISEHIR", product="Brimoder",
            target=200, company=0, competitor=150,
        ),
    }
    dashboard = {
        "executive_metrics": {
            "products": [
                {"product_name": "Fentivag", "unit_actual": 0, "actual_tl": 0},
                {"product_name": "Brimoder", "unit_actual": 1250, "actual_tl": 250000},
            ]
        }
    }

    rows = RegionAISnapshotService._zero_exit_bricks(
        workspaces, dashboard_payload=dashboard
    )

    assert [row["product_name"] for row in rows] == ["Brimoder"]
    assert rows[0]["brick"] == "DIYARBAKIR YENISEHIR"


def test_city_pressure_marks_missing_previous_competitor_data_explicitly():
    result = RegionAISnapshotService.build(
        report={"periods": {"monthly": {"products": []}}},
        market_analysis={
            "rival_rows": [{
                "name": "Rakip",
                "cities": [{"city": "DIYARBAKIR", "unit": 100}],
            }]
        },
        dashboard_payload={"executive_metrics": {"products": []}},
        previous_market_analysis={},
        current_workspaces={},
        previous_workspaces={},
        year=2026,
        month=9,
    )

    assert result["city_pressure"] == []
    assert result["city_pressure_state"] == "NO_PREVIOUS_DATA"
    assert result["previous_competitor_available"] is False


def test_city_pressure_distinguishes_existing_previous_data_from_no_growth():
    result = RegionAISnapshotService.build(
        report={"periods": {"monthly": {"products": []}}},
        market_analysis={
            "rival_rows": [{
                "name": "Rakip",
                "cities": [{"city": "DIYARBAKIR", "unit": 80}],
            }]
        },
        dashboard_payload={"executive_metrics": {"products": []}},
        previous_market_analysis={
            "rival_rows": [{
                "name": "Rakip",
                "cities": [{"city": "DIYARBAKIR", "unit": 100}],
            }]
        },
        current_workspaces={},
        previous_workspaces={},
        year=2026,
        month=9,
    )

    assert result["city_pressure"] == []
    assert result["city_pressure_state"] == "NO_GROWTH"
    assert result["previous_competitor_available"] is True

def test_city_pressure_falls_back_to_published_representative_brick_snapshots():
    current_workspaces = {
        1: _workspace(
            brick="DIYARBAKIR YENISEHIR", product="Monurol",
            company=30, competitor=110, share=21,
        )
    }
    previous_workspaces = {
        1: _workspace(
            brick="DIYARBAKIR YENISEHIR", product="Monurol",
            company=20, competitor=100, share=17,
        )
    }

    result = RegionAISnapshotService.build(
        report={"periods": {"monthly": {"products": []}}},
        market_analysis={},
        dashboard_payload={"executive_metrics": {"products": []}},
        previous_market_analysis={},
        current_workspaces=current_workspaces,
        previous_workspaces=previous_workspaces,
        year=2026,
        month=9,
    )

    assert result["city_pressure_state"] == "HAS_ROWS"
    assert result["previous_competitor_available"] is True
    assert result["city_pressure"][0]["city"] == "DIYARBAKIR"
    assert result["city_pressure"][0]["previous_unit"] == 100.0
    assert result["city_pressure"][0]["current_unit"] == 110.0

