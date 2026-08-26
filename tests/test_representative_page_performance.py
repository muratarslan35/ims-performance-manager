from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
import threading
import time
from types import SimpleNamespace

from flask_migrate import upgrade
from sqlalchemy import event, text

from app import create_app
from app.cache.representative_analysis_cache import RepresentativeAnalysisCache
from app.extensions import db
from app.models import CompetitionData, IMSRawData, IMSUpload, Product, Representative, RepresentativeBrickAssignment
from app.services.competitive_intelligence_service import CompetitiveIntelligenceService
from app.services.representative_market_service import RepresentativeMarketService
import verify_representative_performance as performance_gate


MIGRATIONS_DIR = str(Path(__file__).resolve().parents[1] / "migrations")


def _app(tmp_path):
    class Config:
        TESTING = True
        SECRET_KEY = "representative-performance-test"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'representative-performance.db'}"
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


def _competition(upload_id, year, month, brick, product_name, value, source_row):
    return CompetitionData(
        upload_id=upload_id,
        year=year,
        month=month,
        sheet_name="AYLIK REKABET KUTU",
        period_type="MONTHLY",
        territory="901 DIYARBAKIR",
        subterritory=brick,
        product_group="TRAVAZOL GRUP",
        product_name=product_name,
        metric_type="UNIT",
        metric_value=value,
        is_subtotal=False,
        is_grand_total=False,
        source_row=source_row,
    )


def test_market_competition_query_is_scoped_in_sql(tmp_path):
    application = _app(tmp_path)
    with application.app_context():
        representative = Representative(rep_code="PERF1", rep_name="PERF TEMSILCI", active=True)
        db.session.add(representative)
        db.session.flush()
        upload = IMSUpload(
            file_name="perf.xlsx", year=2026, month=8, quarter="Q3", status="COMPLETED",
            completed_at=datetime(2026, 8, 20, 10, 0),
        )
        db.session.add(upload)
        db.session.flush()
        db.session.add(RepresentativeBrickAssignment(
            representative_id=representative.id, year=2026, month=8, brick="BRICK A", active=True
        ))
        db.session.add(_competition(upload.id, 2026, 8, "BRICK A", "RAKIP A", 75, 1))
        for index in range(200):
            db.session.add(_competition(
                upload.id, 2026, 8, f"NOISE {index:03d}", f"RAKIP {index:03d}", index + 1, index + 2
            ))
        db.session.commit()

        statements = []
        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if "ims_competition_data" in statement:
                statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", capture)
        try:
            service = RepresentativeMarketService(representative, 2026, 8)
            upload_id, rows = service._competition_rows({service._key("BRICK A")}, set())
        finally:
            event.remove(db.engine, "before_cursor_execute", capture)

        assert upload_id == upload.id
        assert len(rows) == 1
        assert rows[0].subterritory == "BRICK A"
        select_statements = [statement for statement in statements if statement.lstrip().upper().startswith("SELECT")]
        assert len(select_statements) == 1
        normalized = " ".join(select_statements[0].upper().split())
        assert "SUBTERRITORY IN" in normalized
        assert "METRIC_TYPE" in normalized


def test_competitive_intelligence_batches_six_months_into_one_competition_query(tmp_path):
    application = _app(tmp_path)
    with application.app_context():
        representative = Representative(rep_code="PERF2", rep_name="PERF TEMSILCI 2", active=True)
        product = Product(
            product_code="TRAVAZOL", product_name="Travazol", ims_name="TRAVAZOL",
            competitor_group="TRAVAZOL GRUP", is_active=True,
        )
        db.session.add_all([representative, product])
        db.session.flush()
        db.session.add(RepresentativeBrickAssignment(
            representative_id=representative.id, year=2026, month=8, brick="BRICK A", active=True
        ))

        base = datetime(2026, 3, 1, 8, 0)
        uploads = []
        for month in range(3, 9):
            upload = IMSUpload(
                file_name=f"month-{month}.xlsx", year=2026, month=month, quarter="Q2" if month <= 6 else "Q3",
                status="COMPLETED", completed_at=base + timedelta(days=month * 2),
            )
            db.session.add(upload)
            db.session.flush()
            uploads.append(upload)
            db.session.add(_competition(upload.id, 2026, month, "BRICK A", "RAKIP A", month * 10, month))
            db.session.add(_competition(upload.id, 2026, month, "NOISE", "RAKIP NOISE", 9999, month + 50))

        previous_august = IMSUpload(
            file_name="august-previous.xlsx", year=2026, month=8, quarter="Q3", status="COMPLETED",
            completed_at=uploads[-1].completed_at - timedelta(hours=1),
        )
        db.session.add(previous_august)
        db.session.flush()
        db.session.add(_competition(previous_august.id, 2026, 8, "BRICK A", "RAKIP A", 10, 99))
        db.session.commit()

        statements = []
        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if "ims_competition_data" in statement and statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", capture)
        try:
            result = CompetitiveIntelligenceService(representative.id, 2026, 8).build()
        finally:
            event.remove(db.engine, "before_cursor_execute", capture)

        assert len(result["compared_uploads"]) == 2
        assert len(statements) == 1
        normalized = " ".join(statements[0].upper().split())
        assert "GROUP BY" in normalized
        assert "UPLOAD_ID IN" in normalized
        assert "SUBTERRITORY IN" in normalized
        assert result["weekly_alerts"][0]["brick"] == "BRICK A"
        assert all(item.get("brick") != "NOISE" for item in result["weekly_alerts"])


def test_representative_cache_coalesces_concurrent_misses():
    RepresentativeAnalysisCache.clear()
    counter = 0
    counter_lock = threading.Lock()

    def loader():
        nonlocal counter
        with counter_lock:
            counter += 1
        time.sleep(0.05)
        return {"value": 42}

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(
                RepresentativeAnalysisCache.get_or_compute,
                "representative-single-flight",
                loader,
                ttl_seconds=30,
                force_enable=True,
            )
            for _ in range(8)
        ]
        results = [future.result() for future in futures]

    assert counter == 1
    assert results == [{"value": 42}] * 8
    RepresentativeAnalysisCache.clear()


def test_representative_read_indexes_are_used(tmp_path):
    application = _app(tmp_path)
    with application.app_context():
        competition_plan = "\n".join(str(row[-1]) for row in db.session.execute(text(
            "EXPLAIN QUERY PLAN SELECT subterritory, product_group, product_name, SUM(metric_value) "
            "FROM ims_competition_data WHERE upload_id = 1 AND metric_type = 'UNIT' "
            "AND is_subtotal = 0 AND is_grand_total = 0 AND subterritory = 'BRICK A' "
            "GROUP BY upload_id, subterritory, product_group, product_name"
        )).all())
        raw_plan = "\n".join(str(row[-1]) for row in db.session.execute(text(
            "EXPLAIN QUERY PLAN SELECT product_id, brick, sheet_type, unit FROM ims_raw_data "
            "WHERE upload_id = 1 AND sheet_type = 'brick_sales' AND brick = 'BRICK A'"
        )).all())

        assert "ix_competition_upload_metric_flags_subterritory" in competition_plan
        assert "ix_ims_raw_upload_sheet_brick" in raw_plan


def test_performance_gate_first_run_is_separate_and_clears_result_cache(tmp_path, monkeypatch):
    application = _app(tmp_path)
    with application.app_context():
        calls = []
        monkeypatch.setattr(
            performance_gate,
            "_build_read_model",
            lambda representative, year, month: calls.append((representative.id, year, month)),
        )
        RepresentativeAnalysisCache.get_or_compute(
            "first-run-sentinel", lambda: {"cached": True}, force_enable=True
        )

        result = performance_gate.warmup_runtime(
            SimpleNamespace(id=77, rep_name="PERF WARMUP"), 2026, 8
        )

        assert calls == [(77, 2026, 8)]
        assert result["representative_id"] == 77
        assert result["seconds"] >= 0
        assert result["selects"] == 0
        assert result["competition_selects"] == 0
        assert not RepresentativeAnalysisCache._store
