from app.services.scoped_ai_insight_service import ScopedAIInsightService


def test_representative_ai_filters_team4_and_total_market_rows():
    payload = {
        "weekly_alerts": [
            {"brick": "MARDIN BATI ILCELER - EKIP 4 TOPLAM PAZAR", "product": "FUGGY", "delta_unit": 100},
            {"brick": "MARDIN MERKEZ", "product": "ZALAIN", "delta_unit": 25, "previous_unit": 10, "current_unit": 35},
        ],
        "monthly_trends": [
            {"group": "TRAVAZOL GRUBU", "side": "EKIP 4 TOPLAM PAZAR", "delta_unit": 50},
            {"group": "TRAVAZOL GRUBU", "side": "Rakip", "delta_unit": -8},
        ],
        "own_gaps": [
            {"brick": "SIRNAK MERKEZ", "group": "MONUROL", "competitor_unit": 12},
        ],
    }

    clean = ScopedAIInsightService._sanitize_competitive_intelligence(payload)

    assert [row["product"] for row in clean["weekly_alerts"]] == ["ZALAIN"]
    assert [row["side"] for row in clean["monthly_trends"]] == ["Rakip"]
    assert len(clean["own_gaps"]) == 1


def test_region_ai_builds_city_level_performance_and_analysis():
    periods = {
        "monthly": {
            "label": "Aylık",
            "target_tl": 300.0,
            "actual_tl": 240.0,
            "gap_tl": 60.0,
            "realization_percent": 80.0,
            "complete": True,
            "products": [],
            "representatives": [
                {"representative_name": "A", "city": "DIYARBAKIR", "target_tl": 100.0, "actual_tl": 60.0, "gap_tl": 40.0, "realization_percent": 60.0, "complete": True},
                {"representative_name": "B", "city": "DIYARBAKIR", "target_tl": 100.0, "actual_tl": 90.0, "gap_tl": 10.0, "realization_percent": 90.0, "complete": True},
                {"representative_name": "C", "city": "MARDIN", "target_tl": 100.0, "actual_tl": 90.0, "gap_tl": 10.0, "realization_percent": 90.0, "complete": True},
            ],
        }
    }

    report = ScopedAIInsightService.build(scope_type="region", scope_name="901 DIYARBAKIR", periods=periods)
    monthly = report["periods"]["monthly"]

    assert monthly["province_rows"][0]["city"] == "DIYARBAKIR"
    assert monthly["province_rows"][0]["target_tl"] == 200.0
    assert monthly["province_rows"][0]["actual_tl"] == 150.0
    assert monthly["province_rows"][0]["realization_percent"] == 75.0
    assert any("İl bazında en düşük gerçekleşme DIYARBAKIR" in text for text in monthly["insights"])


def test_ai_keeps_new_q_period_label_instead_of_falling_back_to_old_periods():
    report = ScopedAIInsightService.build(
        scope_type="representative",
        scope_name="TEST",
        periods={
            "q1": {
                "label": "Q1",
                "target_tl": 100.0,
                "actual_tl": 90.0,
                "gap_tl": 10.0,
                "realization_percent": 90.0,
                "complete": True,
                "products": [],
                "representatives": [],
            }
        },
    )

    assert list(report["periods"]) == ["q1"]
    assert report["periods"]["q1"]["label"] == "Q1"
