from app.services.executive_market_cockpit_service import ExecutiveMarketCockpitService


def _snapshot(name, market_unit, company_unit, share, realization):
    return {
        "report": {
            "region_name": name,
            "periods": {
                "monthly": {
                    "target_tl": 100.0,
                    "actual_tl": realization,
                    "realization_percent": realization,
                    "complete": True,
                    "products": [],
                }
            },
            "annual_realization": [],
        },
        "market_analysis": {
            "totals": {
                "market_unit": market_unit,
                "effective_company_unit": company_unit,
                "precise_share_percent": share,
                "competitor_unit": market_unit - company_unit,
            },
            "rival_rows": [],
        },
    }


def test_region_share_gap_uses_weighted_national_unit_share_not_tl_share():
    snapshots = {
        "101": _snapshot("İstanbul", 100.0, 50.0, 50.0, 100.0),
        "201": _snapshot("Kadıköy", 300.0, 60.0, 20.0, 90.0),
    }
    # Deliberately incompatible national TL share. It must not enter the
    # region unit-share comparison.
    market = {"company_share_percent": 80.0, "groups": [], "has_competition": True}

    result = ExecutiveMarketCockpitService.build(market, snapshots)
    monthly = result["periods"]["monthly"]
    rows = {row["region_key"]: row for row in monthly["regions"]}

    assert monthly["national_unit_share_percent"] == 27.5
    assert rows["101"]["unit_share_gap_to_national"] == 22.5
    assert rows["201"]["unit_share_gap_to_national"] == -7.5
    assert "share_gap_to_national" not in rows["101"]


def test_regional_ai_insights_use_existing_snapshot_metrics_without_prediction():
    snapshots = {
        "101": _snapshot("İstanbul", 100.0, 50.0, 50.0, 100.0),
        "201": _snapshot("Kadıköy", 300.0, 60.0, 20.0, 70.0),
    }
    result = ExecutiveMarketCockpitService.build(
        {"company_share_percent": 80.0, "groups": [], "has_competition": True},
        snapshots,
    )
    insights = {row["region_key"]: row for row in result["periods"]["monthly"]["ai_insights"]}

    assert insights["101"]["signal"] == "Hedef üstü · pay avantajlı"
    assert "%100.0" in insights["101"]["metrics"]
    assert "%50.0" in insights["101"]["metrics"]
    assert "+22.5 puan" in insights["101"]["metrics"]
    assert insights["201"]["signal"] == "Öncelikli toparlanma"
    assert "%70.0" in insights["201"]["metrics"]
    assert "-7.5 puan" in insights["201"]["metrics"]
