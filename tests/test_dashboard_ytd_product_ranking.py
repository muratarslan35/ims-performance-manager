from pathlib import Path
from datetime import datetime
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
    assert payload["source"] == "DASHBOARD_SNAPSHOT_YTD_ACCEPTED_ACTUALS"
    assert payload["source_version"] == 2
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
    assert "filename='css/dashboard.css', v='20260919u'" in template
    assert "filename='js/dashboard.js', v='20260919u'" in template
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
    assert "ProductionResultUpload.STATUS_APPLIED" in ranking_query
    assert "selected.actual_unit" in ranking_query
    assert "summary.unit" in ranking_query
    assert "IMSSummary.month <= through_month" in ranking_query

    assert '"ytd_product_rankings": self.query_layer.load_ytd_product_rankings' in service
    assert 'payload["ytd_product_rankings"]' in service
    assert 'existing = (payload or {}).get("ytd_product_rankings")' in route
    assert 'rank_trend_version' in route
    assert 'source_version' in route
    assert "PersistentDashboardSnapshotService.publish" in route


def test_ims_turkey_ranking_is_top_ten_by_realization_with_tl_tiebreaker():
    from app.formatters.dashboard_formatter import DashboardFormatter

    rows = [
        {
            "rep_name": f"Temsilci {index:02d}",
            "city": "İstanbul",
            "actual_tl": 1000 + index,
            "target_tl": 1000,
            "bonus_amount": 0,
        }
        for index in range(12)
    ]
    result = DashboardFormatter().format_top_reps(rows)["top_representatives"]

    assert len(result) == 10
    assert [row["realization_percent"] for row in result] == sorted(
        [row["realization_percent"] for row in result], reverse=True
    )
    assert result[0]["rep_name"] == "Temsilci 11"
    assert result[-1]["rep_name"] == "Temsilci 02"


def test_ims_turkey_ranking_keeps_first_three_collapsed_by_default():
    template = Path("app/templates/dashboard.html").read_text(encoding="utf-8")

    assert 'data-ranking-toggle aria-expanded="false"' in template
    assert "Aylık ₺ realizasyon oranına göre sıralanmıştır." in template


def test_ytd_product_ranking_prefers_accepted_units_and_falls_back_to_monthly_ims(tmp_path):
    from app import create_app
    from app.extensions import db
    from app.models import (
        IMSSummary, Product, ProductionResult, ProductionResultUpload,
        Representative,
    )
    from app.query.dashboard_query import DashboardQuery

    class Config:
        TESTING = True
        SECRET_KEY = "ytd-ranking-source"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'ranking.db'}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = tmp_path / "uploads"
        REPORT_FOLDER = tmp_path / "reports"
        BACKUP_FOLDER = tmp_path / "backups"
        LOG_FOLDER = tmp_path / "logs"
        TEMP_FOLDER = tmp_path / "temp"

    application = create_app(Config)
    with application.app_context():
        db.create_all()
        representative = Representative(
            rep_code="YTD-1", rep_name="YTD TEMSILCI", city="İstanbul",
            region="101", active=True,
        )
        product = Product(
            product_code="TRV-YTD", product_name="Travazol",
            display_order=1, is_active=True,
        )
        db.session.add_all([representative, product])
        db.session.flush()
        db.session.add_all([
            IMSSummary(
                year=2026, month=1, representative_id=representative.id,
                product_id=product.id, unit=4000, tl=1,
            ),
            IMSSummary(
                year=2026, month=2, representative_id=representative.id,
                product_id=product.id, unit=20, tl=1,
            ),
        ])
        upload = ProductionResultUpload(
            file_name="p2.xlsx", stored_file_name="p2.xlsx", source_hash="a" * 64,
            year=2026, month=1, production_stage=2,
            status=ProductionResultUpload.STATUS_APPLIED,
            applied_at=datetime(2026, 1, 31, 12, 0),
        )
        db.session.add(upload)
        db.session.flush()
        db.session.add(ProductionResult(
            upload_id=upload.id, representative_id=representative.id,
            product_id=product.id, realization_percent=50,
            actual_unit=10,
        ))
        db.session.commit()

        rows = DashboardQuery().load_ytd_product_rankings(2026, 2)

        assert len(rows) == 1
        assert rows[0].total_unit == 30

def test_ytd_rank_trend_marks_only_changed_positions():
    current = {
        "products": [{
            "product_key": "TRAVAZOL",
            "rankings": [
                {"representative_id": 1, "rank": 1},
                {"representative_id": 2, "rank": 2},
                {"representative_id": 3, "rank": 3},
            ],
        }]
    }
    previous = {
        "ytd_product_rankings": {
            "products": [{
                "product_key": "TRAVAZOL",
                "rankings": [
                    {"representative_id": 2, "rank": 1},
                    {"representative_id": 1, "rank": 2},
                    {"representative_id": 3, "rank": 3},
                ],
            }]
        }
    }

    result = DashboardService._apply_ytd_rank_trends(current, previous)
    rows = result["products"][0]["rankings"]

    assert rows[0]["rank_direction"] == "up"
    assert rows[0]["rank_change"] == 1
    assert rows[1]["rank_direction"] == "down"
    assert rows[1]["rank_change"] == -1
    assert rows[2]["rank_direction"] is None
    assert rows[2]["rank_change"] == 0


def test_ytd_ranking_ui_rounds_boxes_and_hides_internal_snapshot_word():
    template = Path("app/templates/dashboard.html").read_text(encoding="utf-8")
    javascript = Path("app/static/js/dashboard.js").read_text(encoding="utf-8")

    assert "Snapshot verisi" not in template
    assert "snapshot" not in template.lower()
    assert "Math.round(Number(item.total_unit || 0)).toLocaleString" in javascript
    assert 'ytd-rank-trend up' in javascript
    assert 'ytd-rank-trend down' in javascript

def test_dashboard_period_resolution_does_not_scan_ims_summary_hot_path():
    service = Path("app/services/dashboard_service.py").read_text(encoding="utf-8")
    init_start = service.index("    def __init__(")
    init_end = service.index("    # =========================================================================", init_start)
    init_block = service[init_start:init_end]

    assert "PeriodService.get_active_period" in init_block
    assert "load_last_completed_period" not in init_block
