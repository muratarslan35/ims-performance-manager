import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest
from flask_migrate import upgrade

from app import create_app
from app.extensions import db
from app.models import IMSUpload, Product
from app.services.aggregate_identity_refinement import row_semantic_aggregate_identity
from app.services.dynamic_import_contract import SemanticSheetProfile
from app.services.ims_import_service import IMSImportService
from app.services.official_aggregate_service import OfficialAggregateService


class Config:
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = Path(tempfile.gettempdir()) / "dynamic-aggregate-test-uploads"
    REPORT_FOLDER = Path(tempfile.gettempdir()) / "dynamic-aggregate-test-reports"
    BACKUP_FOLDER = Path(tempfile.gettempdir()) / "dynamic-aggregate-test-backups"
    LOG_FOLDER = Path(tempfile.gettempdir()) / "dynamic-aggregate-test-logs"


def _profile(width=12):
    return SemanticSheetProfile(
        sheet_name="RENAMED SOURCE",
        dataframe=pd.DataFrame(columns=range(width)),
        header_row=0,
        representative_column=0,
        location_column=3,
        product_metrics={1: {"target_tl": 2, "balance_tl": 8, "balance_unit": 11}},
        score=100,
        capability="balance",
    )


def test_row_semantic_identity_ignores_physical_dimension_choice():
    profile = _profile()
    # Week-7 pivot shape: the actual region subtotal identity is repeated at the
    # beginning of several metric blocks while the locator-selected coordinates
    # can be blank/placeholder. Physical coordinates must not decide identity.
    subtotal = pd.Series([
        None, "201 KADIKOY", 1005.0,
        0, "201 KADIKOY", 250.0,
        None, "201 KADIKOY", 600.0,
        None, "201 KADIKOY", 60.0,
    ])
    assert row_semantic_aggregate_identity(profile, subtotal) == (
        "201", "201 KADIKOY"
    )


def test_row_semantic_identity_never_promotes_representative_row_to_region():
    profile = _profile()
    # The region repeats across pivot blocks, but the representative identity is
    # also present. This is a person row, not a regional official subtotal.
    representative = pd.Series([
        "201 KADIKOY", "TEST REPRESENTATIVE", 400.0,
        "201 KADIKOY", "TEST REPRESENTATIVE", 100.0,
        "201 KADIKOY", "TEST REPRESENTATIVE", 200.0,
        "201 KADIKOY", "TEST REPRESENTATIVE", 20.0,
    ])
    assert row_semantic_aggregate_identity(profile, representative) is None


def test_row_semantic_identity_accepts_repeated_national_and_fails_ambiguous_region():
    profile = _profile()
    national = pd.Series([
        None, "NATIONAL", 1005.0,
        None, "NATIONAL", 250.0,
        None, "NATIONAL", 600.0,
        None, "NATIONAL", 60.0,
    ])
    assert row_semantic_aggregate_identity(profile, national) == (
        "NATIONAL", "NATIONAL"
    )

    ambiguous = pd.Series([
        None, "201 KADIKOY", 1005.0,
        None, "301 BURSA", 250.0,
        None, None, 600.0,
        None, None, 60.0,
    ])
    assert row_semantic_aggregate_identity(profile, ambiguous) is None


@pytest.fixture()
def aggregate_env():
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "aggregate.db"
    config = type("RuntimeConfig", (Config,), {"SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}"})
    app = create_app(config)
    ctx = app.app_context()
    ctx.push()
    migrations_dir = str(Path(__file__).resolve().parents[1] / "migrations")
    upgrade(directory=migrations_dir)

    product = Product.query.filter_by(product_code="TRAVAZOL").first()
    if product is None:
        product = Product(product_code="TRAVAZOL", product_name="Travazol", is_active=True)
        db.session.add(product)
    else:
        product.is_active = True
    upload = IMSUpload(
        file_name="week-7-layout.xlsx",
        year=2038,
        month=2,
        week_number=7,
        quarter="Q1",
        status="COMPLETED",
        completed_at=datetime.utcnow(),
    )
    db.session.add(upload)
    db.session.commit()

    try:
        yield temp_dir, app, upload, product
    finally:
        db.session.remove()
        ctx.pop()
        temp_dir.cleanup()


def _week7_style_workbook():
    # Deliberately duplicate hierarchy columns across the balance metric blocks.
    # Person values differ from official subtotal values so an accidental person
    # promotion would immediately break NATIONAL/region reconciliation.
    balance = pd.DataFrame([
        [None, "ŞUBAT HEDEF TL", "TRAVAZOL", None,
         "ŞUBAT ÇIKIŞ TL", "TRAVAZOL", None,
         "ŞUBAT TL BAKİYE", "TRAVAZOL", None,
         "ŞUBAT KUTU BAKİYE", "TRAVAZOL"],
        [None, "NATIONAL", 1005.0, None,
         "NATIONAL", 250.0, None,
         "NATIONAL", 600.0, None,
         "NATIONAL", 60.0],
        [None, "901 DIYARBAKIR", 1005.0, None,
         "901 DIYARBAKIR", 250.0, None,
         "901 DIYARBAKIR", 600.0, None,
         "901 DIYARBAKIR", 60.0],
        ["901 DIYARBAKIR", "DYNAMIC TEST REP", 400.0,
         "901 DIYARBAKIR", "DYNAMIC TEST REP", 100.0,
         "901 DIYARBAKIR", "DYNAMIC TEST REP", 200.0,
         "901 DIYARBAKIR", "DYNAMIC TEST REP", 20.0],
    ])

    weekly = pd.DataFrame([
        [None, None, "1-16 ŞUBAT TL ÇIKIŞI", None,
         "1-16 ŞUBAT KUTU ÇIKIŞI", None,
         "7. HAFTA TL ÇIKIŞI", None],
        [None, None, None, "TRAVAZOL", None, "TRAVAZOL", None, "TRAVAZOL"],
        [None, "NATIONAL", None, 250.0, None, 17.25, None, 99.0],
        [None, "901 DIYARBAKIR", None, 250.0, None, 17.25, None, 99.0],
        ["901 DIYARBAKIR", "DYNAMIC TEST REP", None, 100.0, None, 5.0, None, 10.0],
    ])
    return {
        "BALANCE SOURCE RENAMED": balance,
        "CUMULATIVE SOURCE RENAMED": weekly,
    }


def test_week7_repeated_hierarchy_reconciles_without_weakening_gate(aggregate_env):
    _temp, _app, upload, _product = aggregate_env
    service = IMSImportService("unused.xlsx")
    service.upload = upload
    service.workbook = _week7_style_workbook()

    service.persist_national_dashboard_metrics(2038, 2)
    db.session.commit()

    reconciliation = service.national_region_reconciliation
    assert reconciliation["passed"] is True
    assert reconciliation["targets"]["region_count"] == 1
    assert reconciliation["actuals"]["region_count"] == 1
    assert reconciliation["conflicts"] == []

    national = OfficialAggregateService.product_totals(2038, 2, "NATIONAL")
    region = OfficialAggregateService.product_totals(2038, 2, "901")
    assert national and region
    assert national[0]["target_tl"] == pytest.approx(1005.0)
    assert region[0]["target_tl"] == pytest.approx(1005.0)
    assert national[0]["actual_tl"] == pytest.approx(250.0)
    assert region[0]["actual_tl"] == pytest.approx(250.0)
    assert region[0]["actual_tl"] != pytest.approx(100.0)
