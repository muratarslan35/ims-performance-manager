from pathlib import Path

from app import create_app
from app.extensions import db
from app.models import CompetitionData, IMSSummary, IMSUpload, Product, Representative, Target
from app.services.representative_market_service import RepresentativeMarketService


class Config:
    TESTING = True
    SECRET_KEY = "representative-snapshot-market-canonical"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = Path("/tmp/representative-snapshot-market-canonical/uploads")
    REPORT_FOLDER = Path("/tmp/representative-snapshot-market-canonical/reports")
    BACKUP_FOLDER = Path("/tmp/representative-snapshot-market-canonical/backups")
    LOG_FOLDER = Path("/tmp/representative-snapshot-market-canonical/logs")


def _company_market_row(upload, *, year, month, representative_name, value):
    return CompetitionData(
        upload_id=upload.id,
        year=year,
        month=month,
        sheet_name="AYLIK REKABET KUTU",
        period_type="MONTHLY",
        territory="901 DIYARBAKIR",
        subterritory=representative_name,
        product_group="BRIMODER GRUP",
        product_name="BRIMODER",
        metric_type="UNIT",
        metric_value=value,
        is_subtotal=False,
        is_grand_total=False,
        source_row=1,
    )


def test_background_snapshot_uses_canonical_boxes_market_and_previous_month():
    app = create_app(Config)
    with app.app_context():
        db.create_all()
        representative = Representative(
            rep_code="DIY-MURAT",
            rep_name="Murat Arslan",
            region="901",
            city="Diyarbakır",
            active=True,
        )
        product = Product(
            product_code="BRIMODER",
            product_name="Brimoder",
            ims_name="BRIMODER",
            competitor_group="BRIMODER GRUP",
            unit_price=827.56,
            display_order=1,
            is_active=True,
        )
        db.session.add_all([representative, product])
        db.session.flush()

        march = IMSUpload(
            file_name="13.Hafta.xlsx",
            year=2026,
            month=3,
            week_number=13,
            status="COMPLETED",
        )
        april = IMSUpload(
            file_name="16.Hafta.xlsx",
            year=2026,
            month=4,
            week_number=16,
            status="COMPLETED",
        )
        db.session.add_all([march, april])
        db.session.flush()

        db.session.add_all(
            [
                Target(
                    year=2026,
                    month=3,
                    quarter="Q1",
                    representative_id=representative.id,
                    product_id=product.id,
                    tl_target=8275.60,
                    unit_target=10,
                ),
                IMSSummary(
                    upload_id=march.id,
                    year=2026,
                    month=3,
                    quarter="Q1",
                    representative_id=representative.id,
                    product_id=product.id,
                    target_tl=8275.60,
                    target_unit=10,
                    tl=16551.20,
                    unit=20,
                ),
                _company_market_row(
                    march,
                    year=2026,
                    month=3,
                    representative_name=representative.rep_name,
                    value=100,
                ),
                Target(
                    year=2026,
                    month=4,
                    quarter="Q2",
                    representative_id=representative.id,
                    product_id=product.id,
                    tl_target=13512.00,
                    # Deliberately correct stored target: canonical TL/price is 16.
                    unit_target=16,
                ),
                IMSSummary(
                    upload_id=april.id,
                    year=2026,
                    month=4,
                    quarter="Q2",
                    representative_id=representative.id,
                    product_id=product.id,
                    target_tl=13512.00,
                    target_unit=16,
                    tl=9931.00,
                    # Deliberately corrupt legacy unit reproducing the live bug.
                    unit=703,
                ),
                # The workbook market denominator is 268. With legacy own unit
                # 703 the old path produced competitor=0/share=262%. The guarded
                # snapshot must replace own boxes with 12, keep market=268 and
                # therefore reconcile competitor=256.
                _company_market_row(
                    april,
                    year=2026,
                    month=4,
                    representative_name=representative.rep_name,
                    value=268,
                ),
            ]
        )
        db.session.commit()

        # No Flask request context: this is the same execution shape used by the
        # persistent representative snapshot worker/backfill.
        result = RepresentativeMarketService(representative, 2026, 4).build()
        brimoder = next(
            row for row in result["rows"] if row["product"].product_code == "BRIMODER"
        )

        assert brimoder["target_unit"] == 16
        assert brimoder["actual_unit"] == 12
        assert brimoder["competitor_unit"] == 256
        assert brimoder["market_unit"] == 268
        assert brimoder["share_percent"] == 4.5
        assert brimoder["market_unit"] == brimoder["actual_unit"] + brimoder["competitor_unit"]

        assert brimoder["has_previous"] is True
        assert brimoder["previous_actual_unit"] == 20
        assert brimoder["previous_competitor_unit"] == 80
        assert brimoder["actual_change_unit"] == -8
        assert brimoder["competitor_change_unit"] == 176

        assert result["totals"]["actual_unit"] == 12
        assert result["totals"]["competitor_unit"] == 256
        assert result["totals"]["market_unit"] == 268
        assert result["totals"]["market_unit"] == (
            result["totals"]["actual_unit"] + result["totals"]["competitor_unit"]
        )

        db.session.remove()
        db.drop_all()
