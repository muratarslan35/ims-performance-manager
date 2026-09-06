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
    market = {"company_share_percent": 80.0, "groups": [], "has_competition": True}

    result = ExecutiveMarketCockpitService.build(market, snapshots)
    monthly = result["periods"]["monthly"]
    rows = {row["region_key"]: row for row in monthly["regions"]}

    assert monthly["national_unit_share_percent"] == 27.5
    assert rows["101"]["unit_share_gap_to_national"] == 22.5
    assert rows["201"]["unit_share_gap_to_national"] == -7.5
    assert "share_gap_to_national" not in rows["101"]


def test_regional_ai_insights_carry_real_snapshot_values_without_prediction():
    snapshots = {
        "101": _snapshot("İstanbul", 100.0, 50.0, 50.0, 100.0),
        "201": _snapshot("Kadıköy", 300.0, 60.0, 20.0, 70.0),
    }
    result = ExecutiveMarketCockpitService.build(
        {"company_share_percent": 80.0, "groups": [], "has_competition": True},
        snapshots,
    )
    insights = {row["region_key"]: row for row in result["periods"]["monthly"]["ai_insights"]}

    istanbul = insights["101"]
    assert istanbul["signal"] == "Hedef üstü · pay avantajlı"
    assert istanbul["period_label"] == "Aylık"
    assert istanbul["target_tl"] == 100.0
    assert istanbul["actual_tl"] == 100.0
    assert istanbul["realization_percent"] == 100.0
    assert istanbul["company_unit"] == 50.0
    assert istanbul["competitor_unit"] == 50.0
    assert istanbul["market_unit"] == 100.0
    assert istanbul["share_percent"] == 50.0
    assert istanbul["unit_share_gap_to_national"] == 22.5

    kadikoy = insights["201"]
    assert kadikoy["signal"] == "Öncelikli toparlanma"
    assert kadikoy["target_tl"] == 100.0
    assert kadikoy["actual_tl"] == 70.0
    assert kadikoy["realization_percent"] == 70.0
    assert kadikoy["company_unit"] == 60.0
    assert kadikoy["competitor_unit"] == 240.0
    assert kadikoy["market_unit"] == 300.0
    assert kadikoy["share_percent"] == 20.0
    assert kadikoy["unit_share_gap_to_national"] == -7.5
