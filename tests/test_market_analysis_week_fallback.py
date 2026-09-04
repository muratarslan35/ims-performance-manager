import tempfile
from datetime import datetime
from pathlib import Path


def _app():
    from app import create_app

    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)

    class Config:
        TESTING = True
        SECRET_KEY = "market-analysis-week-fallback"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{root / 'market.db'}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        LOGIN_DISABLED = True
        UPLOAD_FOLDER = root / "uploads"
        REPORT_FOLDER = root / "reports"
        BACKUP_FOLDER = root / "backups"
        LOG_FOLDER = root / "logs"
        TEMP_FOLDER = root / "temp"

    return create_app(Config), temp


def _competition(upload, group, value, row=1):
    from app.models import CompetitionData

    return CompetitionData(
        upload_id=upload.id,
        year=upload.year,
        month=upload.month,
        week_number=upload.week_number,
        sheet_name=f"competition-{upload.week_number}",
        period_type="WEEKLY",
        territory="NATIONAL",
        subterritory="NATIONAL",
        product_group=group,
        product_name=group,
        metric_type="TL",
        metric_value=value,
        is_subtotal=False,
        is_grand_total=False,
        source_row=row,
    )


def _summary(upload, representative, product, tl):
    from app.models import IMSSummary

    return IMSSummary(
        upload_id=upload.id,
        year=upload.year,
        month=upload.month,
        quarter="Q2",
        representative_id=representative.id,
        product_id=product.id,
        tl=tl,
        unit=10,
    )


def _weekly_fact(upload, representative, product, tl):
    from app.extensions import db
    from app.models import IMSFact, IMSRawData

    raw = IMSRawData(
        upload_id=upload.id,
        year=upload.year,
        month=upload.month,
        quarter="Q2",
        week_number=upload.week_number,
        sheet_name="TTS",
        sheet_type="brick_sales",
        source_row=1,
        representative_id=representative.id,
        product_id=product.id,
        representative=representative.rep_name,
        product=product.product_name,
        raw_json="{}",
    )
    db.session.add(raw)
    db.session.flush()
    return IMSFact(
        upload_id=upload.id,
        raw_data_id=raw.id,
        representative_id=representative.id,
        product_id=product.id,
        year=upload.year,
        month=upload.month,
        quarter="Q2",
        week_number=upload.week_number,
        report_type="brick_sales",
        unit=10,
        tl=tl,
        metrics_json="{}",
    )


def test_current_week_deduplicates_same_company_product():
    app, temp = _app()
    try:
        with app.app_context():
            from app.extensions import db
            from app.models import IMSUpload, Product, Representative
            from app.services.market_analysis_service import MarketAnalysisService

            db.create_all()
            product = Product(product_code="TRAVAZOL", product_name="Travazol", ims_name="TRAVAZOL", is_active=True, display_order=1)
            representative = Representative(rep_code="R1", rep_name="Rep 1", active=True)
            db.session.add_all([product, representative]); db.session.flush()
            upload = IMSUpload(file_name="17.xlsx", year=2026, month=4, week_number=17, status="COMPLETED", completed_at=datetime(2026, 4, 30))
            db.session.add(upload); db.session.flush()
            db.session.add_all([
                _summary(upload, representative, product, 72_000_000),
                _competition(upload, "TRAVAZOL GROUP", 188_000_000, 1),
                _competition(upload, "TRAVAZOL GRUBU (KREM PAZARI)", 219_000_000, 2),
            ])
            db.session.commit()

            result = MarketAnalysisService(2026, 4).build()

            rows = [row for row in result["groups"] if row["company_product"] == "Travazol"]
            assert len(rows) == 1
            assert rows[0]["market_sales_tl"] == 219_000_000
            assert result["source_state"] == "CURRENT"
            assert result["source_week"] == 17
            assert "17. hafta IMS dosyasından" in result["source_message"]
    finally:
        temp.cleanup()


def test_missing_current_competition_falls_back_to_previous_week_as_one_snapshot():
    app, temp = _app()
    try:
        with app.app_context():
            from app.extensions import db
            from app.models import IMSUpload, Product, Representative
            from app.services.market_analysis_service import MarketAnalysisService

            db.create_all()
            product = Product(product_code="MONUROL", product_name="Monurol", ims_name="MONUROL", is_active=True, display_order=1)
            representative = Representative(rep_code="R2", rep_name="Rep 2", active=True)
            db.session.add_all([product, representative]); db.session.flush()
            week16 = IMSUpload(file_name="16.xlsx", year=2026, month=4, week_number=16, status="COMPLETED", completed_at=datetime(2026, 4, 23))
            week17 = IMSUpload(file_name="17.xlsx", year=2026, month=4, week_number=17, status="COMPLETED", completed_at=datetime(2026, 4, 30))
            db.session.add_all([week16, week17]); db.session.flush()
            db.session.add_all([
                _weekly_fact(week16, representative, product, 20_000_000),
                _competition(week16, "MONUROL GRUBU", 100_000_000),
                _summary(week17, representative, product, 27_000_000),
            ])
            db.session.commit()

            result = MarketAnalysisService(2026, 4).build()
            row = next(item for item in result["groups"] if item["company_product"] == "Monurol")

            assert result["source_state"] == "FALLBACK"
            assert result["latest_week"] == 17
            assert result["source_week"] == 16
            assert row["company_sales_tl"] == 20_000_000
            assert row["market_sales_tl"] == 100_000_000
            assert "17. hafta IMS verisinde rakip analizi mevcut değil" in result["source_message"]
            assert "16. hafta IMS dosyasına aittir" in result["source_message"]
    finally:
        temp.cleanup()


def test_month_without_competition_keeps_company_ims_and_marks_market_unavailable():
    app, temp = _app()
    try:
        with app.app_context():
            from app.extensions import db
            from app.models import IMSUpload, Product, Representative
            from app.services.market_analysis_service import MarketAnalysisService

            db.create_all()
            product = Product(product_code="ACNEMIX", product_name="Acnemix", ims_name="ACNEMIX", is_active=True, display_order=1)
            representative = Representative(rep_code="R3", rep_name="Rep 3", active=True)
            db.session.add_all([product, representative]); db.session.flush()
            upload = IMSUpload(file_name="17-no-competition.xlsx", year=2026, month=4, week_number=17, status="COMPLETED", completed_at=datetime(2026, 4, 30))
            db.session.add(upload); db.session.flush()
            db.session.add(_summary(upload, representative, product, 7_500_000))
            db.session.commit()

            result = MarketAnalysisService(2026, 4).build()
            row = next(item for item in result["groups"] if item["company_product"] == "Acnemix")

            assert result["source_state"] == "IMS_ONLY"
            assert result["has_competition"] is False
            assert row["company_sales_tl"] == 7_500_000
            assert row["market_available"] is False
            assert row["market_sales_tl"] is None
            assert row["competitor_sales_tl"] is None
    finally:
        temp.cleanup()


def test_dashboard_market_panel_is_hidden_and_dedicated_page_has_source_banner():
    shell_css = Path("app/static/css/shell-enhancements.css").read_text(encoding="utf-8")
    market_template = Path("app/templates/market_analysis.html").read_text(encoding="utf-8")
    assert ".executive-market-panel { display: none !important; }" in shell_css
    assert "market-source-banner" in market_template
    assert "Her şirket ürünü yalnız bir kez gösterilir" in market_template
