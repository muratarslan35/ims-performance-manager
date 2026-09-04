from pathlib import Path

from app import create_app
from app.extensions import db
from app.models import (
    CompetitionData,
    IMSRawData,
    IMSSummary,
    IMSUpload,
    Product,
    Representative,
    RepresentativeBrickAssignment,
    Target,
)
from app.services.representative_market_service import RepresentativeMarketService


class Config:
    TESTING = True
    SECRET_KEY = "representative-market-consistency"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = Path("/tmp/representative-market-consistency/uploads")
    REPORT_FOLDER = Path("/tmp/representative-market-consistency/reports")
    BACKUP_FOLDER = Path("/tmp/representative-market-consistency/backups")
    LOG_FOLDER = Path("/tmp/representative-market-consistency/logs")


def _competition(upload, *, year, month, brick, name, value, subterritory=None):
    return CompetitionData(
        upload_id=upload.id,
        year=year,
        month=month,
        sheet_name="AYLIK REKABET KUTU",
        period_type="MONTHLY",
        territory="901 DIYARBAKIR",
        subterritory=subterritory or brick,
        product_group="BRIMODER GRUP",
        product_name=name,
        metric_type="UNIT",
        metric_value=value,
        is_subtotal=False,
        is_grand_total=False,
        source_row=1,
    )


def test_representative_market_reconciles_named_rivals_and_previous_period_scope():
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
            file_name="13.Hafta.xlsx", year=2026, month=3, week_number=13, status="COMPLETED"
        )
        april = IMSUpload(
            file_name="16.Hafta.xlsx", year=2026, month=4, week_number=16, status="COMPLETED"
        )
        db.session.add_all([march, april])
        db.session.flush()

        db.session.add_all([
            RepresentativeBrickAssignment(
                representative_id=representative.id,
                year=2026,
                month=3,
                brick="MARDIN ESKI",
                active=True,
            ),
            RepresentativeBrickAssignment(
                representative_id=representative.id,
                year=2026,
                month=4,
                brick="MARDIN YENI",
                active=True,
            ),
            Target(
                year=2026,
                month=4,
                quarter="Q2",
                representative_id=representative.id,
                product_id=product.id,
                tl_target=12413.40,
                unit_target=999,
                tl_realization=26481.92,
                unit_realization=700,
            ),
            IMSSummary(
                upload_id=april.id,
                year=2026,
                month=4,
                quarter="Q2",
                representative_id=representative.id,
                product_id=product.id,
                target_tl=12413.40,
                target_unit=999,
                tl=26481.92,
                unit=700,
            ),
            IMSRawData(
                upload_id=march.id,
                year=2026,
                month=3,
                quarter="Q1",
                sheet_name="BRICK SATIS",
                sheet_type="brick_sales",
                source_row=1,
                representative=representative.rep_name,
                representative_id=representative.id,
                product=product.product_name,
                product_id=product.id,
                brick="MARDIN ESKI",
                unit=20,
                tl=16000,
                raw_json="{}",
            ),
            # Representative aggregate contains only company total. Before this
            # repair it made Brimoder competitor total appear as zero.
            _competition(
                april,
                year=2026,
                month=4,
                brick="MARDIN YENI",
                subterritory=representative.rep_name,
                name="BRIMODER",
                value=32,
            ),
            _competition(april, year=2026, month=4, brick="MARDIN YENI", name="BRIMODER", value=32),
            _competition(april, year=2026, month=4, brick="MARDIN YENI", name="ROZA (KREM&JEL)", value=287),
            _competition(march, year=2026, month=3, brick="MARDIN ESKI", name="BRIMODER", value=20),
            _competition(march, year=2026, month=3, brick="MARDIN ESKI", name="ROZA (KREM&JEL)", value=100),
        ])
        db.session.commit()

        with app.test_request_context(f"/representatives/view/{representative.id}"):
            result = RepresentativeMarketService(representative, 2026, 4).build()

        brimoder = result["rows"][0]
        assert brimoder["product"].product_code == "BRIMODER"

        # Current own boxes follow April TL/price authority, not corrupt legacy unit.
        assert float(brimoder["actual_unit"]) == 32
        assert brimoder["target_unit"] == 15

        # Named rival detail, product table and total market must reconcile.
        assert brimoder["rivals"] == [{"name": "ROZA (KREM&JEL)", "unit": 287.0}]
        assert float(brimoder["competitor_unit"]) == 287
        assert float(brimoder["market_unit"]) == 319
        assert brimoder["share_percent"] == 10.0

        # Previous month uses that month's brick membership and retained DB rows.
        assert brimoder["has_previous"] is True
        assert float(brimoder["previous_actual_unit"]) == 20
        assert float(brimoder["previous_competitor_unit"]) == 100
        assert float(brimoder["actual_change_unit"]) == 12
        assert float(brimoder["competitor_change_unit"]) == 187

        # Display formatting remains numeric but is unambiguous for Turkish users.
        assert format(brimoder["actual_unit"], ",.0f") == "32"
        assert format(type(brimoder["actual_unit"])(9360), ",.0f") == "9.360"

        # KPI totals consume exactly the same corrected product values.
        assert float(result["totals"]["actual_unit"]) == 32
        assert float(result["totals"]["competitor_unit"]) == 287
        assert float(result["totals"]["market_unit"]) == 319

        db.session.remove()
        db.drop_all()
