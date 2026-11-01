from datetime import datetime
from pathlib import Path
import pytest

from flask_migrate import upgrade
from sqlalchemy import event

from app import create_app
from app.extensions import db
from app.models import CompetitionData, IMSRawData, IMSUpload, Product, Representative, RepresentativeBrickAssignment
from app.services.representative_market_service import RepresentativeMarketService


MIGRATIONS_DIR = str(Path(__file__).resolve().parents[1] / "migrations")


def _app(tmp_path):
    class Config:
        TESTING = True
        SECRET_KEY = "representative-market-memo-test"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'representative-market-memo.db'}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = False
        UPLOAD_FOLDER = tmp_path / "uploads"
        REPORT_FOLDER = tmp_path / "reports"
        BACKUP_FOLDER = tmp_path / "backups"
        LOG_FOLDER = tmp_path / "logs"
        TEMP_FOLDER = tmp_path / "temp"

    application = create_app(Config)
    with application.app_context():
        upgrade(directory=MIGRATIONS_DIR)
    return application


def test_market_build_paths_reuse_current_upload_and_scope_queries(tmp_path):
    """Current-period upload identity and brick scope are read once per service build.

    The market view consumes the same period in aggregate competition, raw brick
    and exact brick competition paths. Those paths must share request-local
    identity/scope reads instead of repeating identical SELECTs.
    """
    application = _app(tmp_path)
    with application.app_context():
        representative = Representative(
            rep_code="MEMO1",
            rep_name="MEMO TEMSILCI",
            region="901 DIYARBAKIR",
            city="DIYARBAKIR",
            territory="BRICK A",
            active=True,
        )
        product = Product(
            product_code="TRAVAZOL",
            product_name="Travazol",
            ims_name="TRAVAZOL",
            competitor_group="TRAVAZOL GRUP",
            is_active=True,
        )
        db.session.add_all([representative, product])
        db.session.flush()
        upload = IMSUpload(
            file_name="memo.xlsx",
            year=2026,
            month=2,
            quarter="Q1",
            week_number=6,
            status="COMPLETED",
            completed_at=datetime(2026, 2, 10, 10, 0),
        )
        db.session.add(upload)
        db.session.flush()
        db.session.add(
            RepresentativeBrickAssignment(
                representative_id=representative.id,
                year=2026,
                month=2,
                brick="BRICK A",
                active=True,
            )
        )
        db.session.add(
            CompetitionData(
                upload_id=upload.id,
                year=2026,
                month=2,
                sheet_name="AYLIK REKABET KUTU",
                period_type="MONTHLY",
                territory="901 DIYARBAKIR",
                subterritory="BRICK A",
                product_group="TRAVAZOL GRUP",
                product_name="TRAVAZOL",
                metric_type="UNIT",
                metric_value=20,
                is_subtotal=False,
                is_grand_total=False,
                source_row=1,
            )
        )
        db.session.add(
            IMSRawData(
                upload_id=upload.id,
                year=2026,
                month=2,
                quarter="Q1",
                sheet_name="BRICK SATIS",
                sheet_type="brick_sales",
                source_row=1,
                representative="MEMO TEMSILCI",
                representative_id=representative.id,
                product="Travazol",
                product_id=product.id,
                brick="BRICK A",
                unit=10,
                tl=100,
                raw_json="{}",
            )
        )
        db.session.commit()

        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.upper().split()))

        event.listen(db.engine, "before_cursor_execute", capture)
        try:
            service = RepresentativeMarketService(representative, 2026, 2)
            brick_key = service._key("BRICK A")
            service._competition_rows({brick_key}, set())
            service._brick_raw_rows()
            service._brick_competition_rows({brick_key})
        finally:
            event.remove(db.engine, "before_cursor_execute", capture)

        upload_selects = [item for item in statements if " FROM IMS_UPLOADS " in item]
        scope_selects = [
            item for item in statements
            if " FROM REPRESENTATIVE_BRICK_ASSIGNMENTS " in item
            and "SELECT REPRESENTATIVE_BRICK_ASSIGNMENTS.BRICK" in item
        ]

        assert len(upload_selects) == 1
        assert len(scope_selects) == 1


@pytest.mark.parametrize("named,assigned", [(True, True), (False, True), (True, False), (False, False)])
def test_scoped_union_preserves_legacy_rows_without_fetching_discarded_region(named, assigned, tmp_path, monkeypatch):
    from sqlalchemy import or_
    import app.services.representative_query_optimizer as optimizer

    application = _app(tmp_path)
    with application.app_context():
        representative = Representative(rep_code="SCOPE", rep_name="SCOPE REP", region="901", city="CITY", territory="GEO", active=True)
        upload = IMSUpload(file_name="scope.xlsx", year=2026, month=2, quarter="Q1", week_number=6, status="COMPLETED")
        db.session.add_all([representative, upload]);db.session.flush()
        if assigned:
            db.session.add(RepresentativeBrickAssignment(representative_id=representative.id, year=2026, month=2, brick="BRICK A", active=True))
        labels = [("901", "BRICK A"), ("BRICK A", "OTHER"), ("GEO", "FALLBACK")]
        labels += [("901", f"NOISE {i}") for i in range(60)]
        if named:
            labels.append(("901", representative.rep_name))
        for index, (territory, subterritory) in enumerate(labels):
            db.session.add(CompetitionData(upload_id=upload.id, year=2026, month=2, sheet_name="AYLIK REKABET KUTU", period_type="MONTHLY", territory=territory, subterritory=subterritory, product_group="GROUP", product_name="RIVAL", metric_type="UNIT", metric_value=index+1, is_subtotal=False, is_grand_total=False, source_row=index+1))
        db.session.commit()
        service = RepresentativeMarketService(representative, 2026, 2)
        _, brick_keys, fallback_keys = service._scope()
        brick_labels = optimizer._candidate_set(["BRICK A"] if assigned else [])
        geography_labels = optimizer._candidate_set(["901", "CITY", "GEO"])
        representative_labels = optimizer._label_candidates(representative.rep_name)
        legacy = CompetitionData.query.filter(
            CompetitionData.upload_id==upload.id, CompetitionData.metric_type=="UNIT",
            CompetitionData.is_subtotal.is_(False), CompetitionData.is_grand_total.is_(False),
            or_(CompetitionData.subterritory.in_(representative_labels | brick_labels), CompetitionData.territory.in_(geography_labels)),
        ).all()
        expected = [r for r in legacy if service._key(r.subterritory)==service._key(representative.rep_name)]
        if not expected:
            scope_keys = brick_keys or fallback_keys
            expected = [r for r in legacy if service._key(r.subterritory) in scope_keys or service._key(r.territory) in scope_keys]
        fetched=[]
        original=optimizer._namespace_rows
        def capture(rows):
            fetched.append(len(rows))
            return original(rows)
        monkeypatch.setattr(optimizer, "_namespace_rows", capture)
        _, actual = service._competition_rows(brick_keys, fallback_keys)
        assert {r.source_id for r in actual} == {r.id for r in expected}
        detail_ids = {r.id for r in legacy if service._key(r.subterritory) in brick_keys}
        assert fetched == [len({r.id for r in expected} | detail_ids)]
        if assigned:
            _, details = service._brick_competition_rows(brick_keys)
            assert [r.subterritory for r in details] == ["BRICK A"]
