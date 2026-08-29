from decimal import Decimal
from pathlib import Path
import tempfile

import pandas as pd

from app import create_app
from app.extensions import db
from app.models import IMSSummary, IMSUpload, Product, Representative, Target
from app.services.alias_service import AliasService
from app.services.ims_import_service import IMSImportService
from app.services.ims_summary_integrity import synchronize_summary_from_targets
from app.services.week8_read_path_repair import _apply_target_ims_actuals


class BalanceAuthorityTestConfig:
    TESTING = True
    SECRET_KEY = "balance-authority-test"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = Path(tempfile.gettempdir()) / "balance-authority-uploads"
    REPORT_FOLDER = Path(tempfile.gettempdir()) / "balance-authority-reports"
    BACKUP_FOLDER = Path(tempfile.gettempdir()) / "balance-authority-backups"
    LOG_FOLDER = Path(tempfile.gettempdir()) / "balance-authority-logs"


def _setup(balance_value):
    app = create_app(BalanceAuthorityTestConfig)
    ctx = app.app_context()
    ctx.push()
    db.create_all()
    travazol = Product(product_code="TRAVAZOL", product_name="Travazol", is_active=True)
    monurol = Product(product_code="MONUROL", product_name="Monurol", is_active=True)
    rep = Representative(rep_code="BAL-REP", rep_name="BALANCE REP", active=True)
    upload = IMSUpload(file_name="8.Hafta.xlsx", year=2032, month=2, week_number=8, status="COMPLETED")
    db.session.add_all([travazol, monurol, rep, upload])
    db.session.flush()
    target = Target(year=2032, month=2, quarter="Q1", representative_id=rep.id,
                    product_id=travazol.id, tl_target=1003918.0, unit_target=8991.0)
    summary = IMSSummary(upload_id=upload.id, year=2032, month=2, quarter="Q1",
                         representative_id=rep.id, product_id=travazol.id,
                         tl=0.0, unit=0.0, target_tl=1003918.0, target_unit=8991.0)
    db.session.add_all([target, summary])
    db.session.flush()

    service = IMSImportService("unused.xlsx")
    service.upload = upload
    service.workbook = {
        "BAKİYE": pd.DataFrame([
            [None, None, "TL HEDEF", None, "TL ÇIKIŞ", None, "MF'siz KUTU BAKİYE", None],
            ["BÖLGE", "TTS İSMİ", "TRAVAZOL", "MONUROL", "TRAVAZOL", "MONUROL", "TRAVAZOL", "MONUROL"],
            ["901 DIYARBAKIR", "BALANCE REP", 1003918.0, 0.0, 935627.0, 0.0, balance_value, None],
        ]),
        "TTS HAFTALIK ÇIKIŞLARI": pd.DataFrame([
            [None, None, "1-28 ŞUBAT TL ÇIKIŞI", None, "1-28 ŞUBAT KUTU ÇIKIŞI", None],
            [None, None, "TRAVAZOL", "MONUROL", "TRAVAZOL", "MONUROL"],
            ["901 DIYARBAKIR", "BALANCE REP", 935627.0, 0.0, 12146.0, 0.0],
        ]),
    }

    def product_match(name):
        normalized = AliasService.normalize(name)
        product = travazol if normalized == "TRAVAZOL" else monurol if normalized == "MONUROL" else None
        return {"matched": product is not None, "object": product}

    service.resolve_product_match = product_match
    service.resolve_representative_match = lambda name: {
        "matched": AliasService.normalize(name) == "BALANCE REP",
        "object": rep,
    }
    return app, ctx, service, upload, rep, travazol, target, summary


def test_balance_unit_wins_over_conflicting_tts_and_tl_is_unchanged():
    app, ctx, service, upload, rep, product, target, summary = _setup(611.6306)
    try:
        service.apply_balance_summary(2032, 2)
        service.apply_weekly_sales_summary(2032, 2)
        db.session.flush()
        expected = 8991.0 - 611.6306
        assert abs(target.unit_realization - expected) < 1e-9
        assert abs(summary.unit - expected) < 1e-9
        assert target.tl_realization == 935627.0
        assert summary.tl == 935627.0
        assert service.statistics["balance_unit_authority_rows"] == 1

        synchronize_summary_from_targets(upload.id, 2032, 2)
        assert abs(summary.unit - expected) < 1e-9

        rows = {product.id: {"source": "IMS", "complete": True, "target_tl": target.tl_target,
                             "actual_tl": Decimal("935627"), "actual_unit": Decimal("12146")}}
        repaired = _apply_target_ims_actuals(rows, [target], has_completed_ims=True)
        assert abs(float(repaired[product.id]["actual_unit"]) - expected) < 1e-9
    finally:
        db.session.remove()
        db.drop_all()
        ctx.pop()


def test_numeric_zero_balance_is_authoritative_not_tts_fallback():
    app, ctx, service, upload, rep, product, target, summary = _setup(0.0)
    try:
        service.apply_balance_summary(2032, 2)
        service.apply_weekly_sales_summary(2032, 2)
        db.session.flush()
        assert target.unit_realization == 8991.0
        assert summary.unit == 8991.0
        assert target.tl_realization == 935627.0
    finally:
        db.session.remove()
        db.drop_all()
        ctx.pop()


def test_missing_balance_keeps_existing_tts_unit_fallback():
    app, ctx, service, upload, rep, product, target, summary = _setup(None)
    try:
        service.apply_balance_summary(2032, 2)
        service.apply_weekly_sales_summary(2032, 2)
        db.session.flush()
        assert target.unit_realization == 12146.0
        assert summary.unit == 12146.0
        assert target.tl_realization == 935627.0
        assert service.statistics["balance_unit_authority_rows"] == 0
    finally:
        db.session.remove()
        db.drop_all()
        ctx.pop()
