from pathlib import Path
from types import SimpleNamespace

from app.services.dashboard_service import DashboardService


def test_ytd_product_rankings_builds_seven_products_top_ten_and_medal_positions():
    rows = [
        SimpleNamespace(
            product_id=1,
            product_name="Travazol",
            representative_id=index,
            representative_name=f"Temsilci {index:02d}",
            city="İstanbul",
            region="İstanbul",
            total_unit=2000 - index,
        )
        for index in range(1, 13)
    ]
    rows.append(
        SimpleNamespace(
            product_id=1,
            product_name="Travazol",
            representative_id=99,
            representative_name="101 İSTANBUL BOŞ KADRO",
            city="İstanbul",
            region="İstanbul",
            total_unit=9999,
        )
    )

    payload = DashboardService._ytd_product_rankings(rows, 2026, 9)

    assert payload["year"] == 2026
    assert payload["through_month"] == 9
    assert payload["source"] == "DASHBOARD_SNAPSHOT_YTD_IMS_SUMMARY"
    assert [item["product_key"] for item in payload["products"]] == [
        "TRAVAZOL",
        "MONUROL",
        "MIXOVUL",
        "ACNEMIX",
        "STIDERM",
        "BRIMODER",
        "FENTIVAG",
    ]
    travazol = payload["products"][0]
    assert len(travazol["rankings"]) == 10
    assert travazol["rankings"][0]["rank"] == 1
    assert travazol["rankings"][0]["representative_name"] == "Temsilci 01"
    assert all("KADRO" not in item["representative_name"] for item in travazol["rankings"])


def test_ytd_product_ranking_ui_is_snapshot_driven_and_client_switchable():
    template = Path("app/templates/dashboard.html").read_text(encoding="utf-8")
    javascript = Path("app/static/js/dashboard.js").read_text(encoding="utf-8")
    query = Path("app/query/dashboard_query.py").read_text(encoding="utf-8")
    service = Path("app/services/dashboard_service.py").read_text(encoding="utf-8")
    route = Path("app/dashboard.py").read_text(encoding="utf-8")

    assert 'id="ytdProductRankingSection"' in template
    assert 'class="active" data-ytd-limit="5"' in template
    assert 'data-ytd-limit="10"' in template
    assert 'data-ytd-product=' in template
    assert 'first_ytd_rows[:5]' in template
    assert '"ytdProductRankings"' in template
    assert "filename='css/dashboard.css', v='20260919t'" in template
    assert "filename='js/dashboard.js', v='20260919t'" in template
    assert template.index('id="ytdProductRankingSection"') < template.index('id="imsTurkeyRankingSection"')

    assert "initYtdProductRanking" in javascript
    assert "data-ytd-limit" in javascript
    assert "data-ytd-product" in javascript
    assert "let limit = 5" in javascript
    assert 'list.style.transition = "height .28s ease"' in javascript
    assert 'imsRanking.parentElement.insertBefore(ytdRanking, imsRanking)' in javascript
    assert "bi-trophy-fill" in javascript
    assert "bi-award-fill" in javascript
    assert "fetch(" not in javascript[javascript.index("function initYtdProductRanking"):javascript.index("function animateCounters")]

    assert "def load_ytd_product_rankings" in query
    ranking_query = query[query.index("def load_ytd_product_rankings"):query.index("def load_period_performance")]
    assert ranking_query.count("self.session.query(") == 1
    assert "func.sum(IMSSummary.unit)" in ranking_query
    assert "IMSSummary.month <= int(through_month)" in ranking_query

    assert '"ytd_product_rankings": self.query_layer.load_ytd_product_rankings' in service
    assert 'payload["ytd_product_rankings"]' in service
    assert "if isinstance((payload or {}).get(\"ytd_product_rankings\"), dict)" in route
    assert "PersistentDashboardSnapshotService.publish" in route
