from pathlib import Path

from app import create_app
from app.extensions import db
from app.models import IMSSummary, IMSUpload, Product, Representative, Target
from app.services.ims_summary_integrity import synchronize_summary_from_targets


def _test_app(tmp_path):
    class Config:
        TESTING = True
        SECRET_KEY = "ims-summary-integrity"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'summary-integrity.db'}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = Path(tmp_path) / "uploads"
        REPORT_FOLDER = Path(tmp_path) / "reports"
        BACKUP_FOLDER = Path(tmp_path) / "backups"
        LOG_FOLDER = Path(tmp_path) / "logs"
        TEMP_FOLDER = Path(tmp_path) / "temp"

    app = create_app(Config)
    with app.app_context():
        db.create_all()
    return app


def test_summary_integrity_replaces_corrupt_tl_and_unit_from_target_actuals(tmp_path):
    app = _test_app(tmp_path)
    with app.app_context():
        rep = Representative(rep_code="SUM-REP", rep_name="SUMMARY REP", active=True)
        product = Product(product_code="SUM-P", product_name="Summary Product", is_active=True)
        upload = IMSUpload(file_name="8.Hafta.xlsx", year=2026, month=2, week_number=8, status="COMPLETED")
        db.session.add_all([rep, product, upload])
        db.session.flush()

        target = Target(
            year=2026, month=2, quarter="Q1",
            representative_id=rep.id, product_id=product.id,
            tl_target=1003918.0, unit_target=8991.0,
            tl_realization=73689.0, unit_realization=859.0,
        )
        summary = IMSSummary(
            upload_id=upload.id,
            representative_id=rep.id, product_id=product.id,
            year=2026, month=2, quarter="Q1",
            tl=0.0, unit=4298766.48520255,
            target_tl=1003918.0, target_unit=8991.0,
            realization_percent=0.0,
        )
        db.session.add_all([target, summary])
        db.session.commit()

        changed = synchronize_summary_from_targets(upload.id, 2026, 2)
        db.session.commit()
        db.session.refresh(summary)

        assert changed == 1
        assert summary.tl == 73689.0
        assert summary.unit == 859.0
        assert summary.target_tl == 1003918.0
        assert summary.target_unit == 8991.0
        assert summary.realization_percent == 7.34


def test_summary_integrity_preserves_real_numeric_zero(tmp_path):
    app = _test_app(tmp_path)
    with app.app_context():
        rep = Representative(rep_code="ZERO-REP", rep_name="ZERO REP", active=True)
        product = Product(product_code="ZERO-P", product_name="Zero Product", is_active=True)
        upload = IMSUpload(file_name="8.Hafta.xlsx", year=2026, month=2, week_number=8, status="COMPLETED")
        db.session.add_all([rep, product, upload])
        db.session.flush()

        target = Target(
            year=2026, month=2, quarter="Q1",
            representative_id=rep.id, product_id=product.id,
            tl_target=1000.0, unit_target=10.0,
            tl_realization=0.0, unit_realization=0.0,
        )
        summary = IMSSummary(
            upload_id=upload.id,
            representative_id=rep.id, product_id=product.id,
            year=2026, month=2, quarter="Q1",
            tl=999.0, unit=999999.0,
            target_tl=1000.0, target_unit=10.0,
            realization_percent=99.9,
        )
        db.session.add_all([target, summary])
        db.session.commit()

        changed = synchronize_summary_from_targets(upload.id, 2026, 2)
        db.session.commit()
        db.session.refresh(summary)

        assert changed == 1
        assert summary.tl == 0.0
        assert summary.unit == 0.0
        assert summary.realization_percent == 0.0


def test_summary_integrity_does_not_touch_another_period(tmp_path):
    app = _test_app(tmp_path)
    with app.app_context():
        rep = Representative(rep_code="OLD-REP", rep_name="OLD REP", active=True)
        product = Product(product_code="OLD-P", product_name="Old Product", is_active=True)
        feb_upload = IMSUpload(file_name="feb.xlsx", year=2026, month=2, week_number=8, status="COMPLETED")
        jan_upload = IMSUpload(file_name="jan.xlsx", year=2026, month=1, week_number=4, status="COMPLETED")
        db.session.add_all([rep, product, feb_upload, jan_upload])
        db.session.flush()

        db.session.add_all([
            Target(
                year=2026, month=2, quarter="Q1",
                representative_id=rep.id, product_id=product.id,
                tl_target=1000.0, unit_target=10.0,
                tl_realization=250.0, unit_realization=2.0,
            ),
            IMSSummary(
                upload_id=feb_upload.id,
                representative_id=rep.id, product_id=product.id,
                year=2026, month=2, quarter="Q1",
                tl=0.0, unit=500000.0,
                target_tl=1000.0, target_unit=10.0,
            ),
            IMSSummary(
                upload_id=jan_upload.id,
                representative_id=rep.id, product_id=product.id,
                year=2026, month=1, quarter="Q1",
                tl=123.0, unit=4.0,
                target_tl=900.0, target_unit=9.0,
            ),
        ])
        db.session.commit()

        changed = synchronize_summary_from_targets(feb_upload.id, 2026, 2)
        db.session.commit()

        feb = IMSSummary.query.filter_by(year=2026, month=2).one()
        jan = IMSSummary.query.filter_by(year=2026, month=1).one()
        assert changed == 1
        assert (feb.tl, feb.unit) == (250.0, 2.0)
        assert (jan.tl, jan.unit) == (123.0, 4.0)
