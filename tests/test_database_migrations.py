import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from flask_migrate import downgrade
from flask_migrate import upgrade
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import OperationalError

from app import create_app
from app.database import initialize_database
from app.extensions import db
from app.models import IMSFact, IMSRawData, IMSSummary, IMSUpload, Product, Representative


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = str(REPO_ROOT / "migrations")
MIGRATION_FILE = (
    REPO_ROOT / "migrations" / "versions" / "e7e561790e74_harden_schema_migrations.py"
)
MIGRATION_FILE_RECORD_COUNTS = (
    REPO_ROOT
    / "migrations"
    / "versions"
    / "3a7f2e1b9c05_add_ims_uploads_record_count_columns.py"
)
MIGRATION_FILE_REPAIR = (
    REPO_ROOT
    / "migrations"
    / "versions"
    / "9f8b1c2d4e6f_repair_ims_table_column_drift.py"
)


def _create_legacy_schema(db_url):
    engine = sa.create_engine(db_url)
    metadata = sa.MetaData()

    users = sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("full_name", sa.String(150), nullable=False),
        sa.Column("email", sa.String(150), nullable=False),
        sa.Column("password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    representatives = sa.Table(
        "representatives",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("rep_name", sa.String(150), nullable=False),
    )
    products = sa.Table(
        "products",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("product_name", sa.String(150), nullable=False),
    )
    settings = sa.Table(
        "settings",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("setting_key", sa.String(120), nullable=False),
        sa.Column("setting_value", sa.String(255), nullable=False),
    )
    prime_rules = sa.Table(
        "prime_rules",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("required_percent", sa.Integer, nullable=False, server_default="90"),
        sa.Column("include_in_prime", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "include_in_total_tl", sa.Boolean, nullable=False, server_default=sa.true()
        ),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("valid_from", sa.Date, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    ims_uploads = sa.Table(
        "ims_uploads",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("month", sa.Integer, nullable=False),
        sa.Column("quarter", sa.String(5), nullable=False),
        sa.Column("sheet_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("raw_record_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("fact_record_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("summary_record_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="PROCESSING"),
        sa.Column("processing_time", sa.Float, nullable=False, server_default="0"),
        sa.Column("uploaded_at", sa.DateTime, nullable=False),
    )
    ims_raw_data = sa.Table(
        "ims_raw_data",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("upload_id", sa.Integer, sa.ForeignKey("ims_uploads.id"), nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("month", sa.Integer, nullable=False),
        sa.Column("quarter", sa.String(5), nullable=False),
        sa.Column("sheet_name", sa.String(150), nullable=False),
        sa.Column("sheet_type", sa.String(50), nullable=False),
        sa.Column("source_row", sa.Integer, nullable=False),
        sa.Column("representative_id", sa.Integer, sa.ForeignKey("representatives.id")),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("products.id")),
        sa.Column("unit", sa.Float, nullable=False, server_default="0"),
        sa.Column("tl", sa.Float, nullable=False, server_default="0"),
        sa.Column("market_share", sa.Float, nullable=False, server_default="0"),
        sa.Column("value_share", sa.Float, nullable=False, server_default="0"),
        sa.Column("growth", sa.Float, nullable=False, server_default="0"),
        sa.Column("raw_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    ims_facts = sa.Table(
        "ims_facts",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("upload_id", sa.Integer, sa.ForeignKey("ims_uploads.id"), nullable=False),
        sa.Column("raw_data_id", sa.Integer, sa.ForeignKey("ims_raw_data.id"), nullable=False),
        sa.Column(
            "representative_id",
            sa.Integer,
            sa.ForeignKey("representatives.id"),
            nullable=False,
        ),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("month", sa.Integer, nullable=False),
        sa.Column("quarter", sa.String(5), nullable=False),
        sa.Column("report_type", sa.String(50), nullable=False),
        sa.Column("unit", sa.Float, nullable=False, server_default="0"),
        sa.Column("tl", sa.Float, nullable=False, server_default="0"),
        sa.Column("market_share", sa.Float, nullable=False, server_default="0"),
        sa.Column("value_share", sa.Float, nullable=False, server_default="0"),
        sa.Column("growth", sa.Float, nullable=False, server_default="0"),
        sa.Column("metrics_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    ims_summary = sa.Table(
        "ims_summary",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("upload_id", sa.Integer, sa.ForeignKey("ims_uploads.id"), nullable=False),
        sa.Column(
            "representative_id",
            sa.Integer,
            sa.ForeignKey("representatives.id"),
            nullable=False,
        ),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("month", sa.Integer, nullable=False),
        sa.Column("quarter", sa.String(5), nullable=False),
        sa.Column("unit", sa.Float, nullable=False, server_default="0"),
        sa.Column("tl", sa.Float, nullable=False, server_default="0"),
        sa.Column("market_share", sa.Float, nullable=False, server_default="0"),
        sa.Column("growth", sa.Float, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    existing_metadata = sa.MetaData()
    existing_metadata.reflect(bind=engine)
    existing_metadata.drop_all(bind=engine, checkfirst=True)
    metadata.create_all(engine)

    with engine.begin() as connection:
        created_at = datetime(2026, 7, 1, 0, 0, 0)
        legacy_user_payload = {
            "id": 1,
            "full_name": "Legacy User",
            "email": "legacy.user@example.com",
            "pass" + "word": "legacy-hash",
            "role": "Representative",
            "active": True,
            "created_at": created_at,
        }
        connection.execute(users.insert().values(**legacy_user_payload))
        connection.execute(representatives.insert().values(id=1, rep_name="Rep 1"))
        connection.execute(products.insert().values(id=1, product_name="Product 1"))
        connection.execute(
            settings.insert().values(id=1, setting_key="MAIN_PRIME", setting_value="50000")
        )
        connection.execute(
            prime_rules.insert().values(
                id=1,
                product_id=1,
                required_percent=90,
                include_in_prime=True,
                include_in_total_tl=True,
                active=True,
                valid_from=datetime(2026, 1, 1).date(),
                created_at=created_at,
            )
        )
        connection.execute(
            ims_uploads.insert().values(
                id=1,
                file_name="ims.xlsx",
                year=2026,
                month=7,
                quarter="Q3",
                uploaded_at=created_at,
            )
        )
        connection.execute(
            ims_summary.insert().values(
                id=1,
                upload_id=1,
                representative_id=1,
                product_id=1,
                year=2026,
                month=7,
                quarter="Q3",
                unit=0,
                tl=0,
                market_share=0,
                growth=0,
                created_at=created_at,
            )
        )
        connection.execute(
            ims_raw_data.insert().values(
                id=1,
                upload_id=1,
                year=2026,
                month=7,
                quarter="Q3",
                sheet_name="BRICK SATIS",
                sheet_type="unknown",
                source_row=2,
                representative_id=1,
                product_id=1,
                raw_json="{}",
                created_at=created_at,
            )
        )
        connection.execute(
            ims_facts.insert().values(
                id=1,
                upload_id=1,
                raw_data_id=1,
                representative_id=1,
                product_id=1,
                year=2026,
                month=7,
                quarter="Q3",
                report_type="BOX",
                metrics_json="{}",
                created_at=created_at,
            )
        )
    engine.dispose()


def _build_test_app(db_url, *, strict_schema_validation=False):
    config = type(
        "MigrationTestConfig",
        (),
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": db_url,
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "STRICT_SCHEMA_VALIDATION": strict_schema_validation,
            "UPLOAD_FOLDER": Path(tempfile.gettempdir()) / "ims-migration-test-uploads",
            "REPORT_FOLDER": Path(tempfile.gettempdir()) / "ims-migration-test-reports",
            "BACKUP_FOLDER": Path(tempfile.gettempdir()) / "ims-migration-test-backups",
            "LOG_FOLDER": Path(tempfile.gettempdir()) / "ims-migration-test-logs",
        },
    )
    return create_app(config)


class DatabaseMigrationsTestCase(unittest.TestCase):
    @staticmethod
    def _has_unique(inspector, table_name, unique_name):
        constraints = {
            item.get("name")
            for item in inspector.get_unique_constraints(table_name)
            if item.get("name")
        }
        if unique_name in constraints:
            return True
        indexes = inspector.get_indexes(table_name)
        return any(index["name"] == unique_name and index.get("unique") for index in indexes)

    @staticmethod
    def _count_rows(connection, table_name):
        return connection.execute(sa.text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()

    def _assert_model_schema_parity(self, inspector):
        model_tables = {
            "representatives": Representative,
            "products": Product,
            "ims_uploads": IMSUpload,
            "ims_raw_data": IMSRawData,
            "ims_facts": IMSFact,
            "ims_summary": IMSSummary,
        }
        for table_name, model in model_tables.items():
            model_columns = {column.name for column in model.__table__.columns}
            db_columns = {column["name"] for column in inspector.get_columns(table_name)}
            self.assertEqual(
                model_columns,
                db_columns,
                f"Schema mismatch for {table_name}: model={sorted(model_columns)} db={sorted(db_columns)}",
            )

    def _assert_required_schema(self, inspector):
        table_names = set(inspector.get_table_names())
        for table_name in {
            "representative_matches",
            "product_matches",
            "manual_match_queue",
            "import_audit_logs",
        }:
            self.assertIn(table_name, table_names)

        ims_upload_columns = [c["name"] for c in inspector.get_columns("ims_uploads")]
        self.assertIn("week_number", ims_upload_columns)
        for col in ("raw_record_count", "fact_record_count", "summary_record_count"):
            self.assertIn(col, ims_upload_columns, f"ims_uploads.{col} is missing")
        self.assertIn("week_number", [c["name"] for c in inspector.get_columns("ims_raw_data")])
        self.assertIn("week_number", [c["name"] for c in inspector.get_columns("ims_facts")])

        indexes = {idx["name"] for idx in inspector.get_indexes("import_audit_logs")}
        self.assertIn("ix_import_audit_upload", indexes)
        self.assertIn("ix_import_audit_period", indexes)

        fact_indexes = {idx["name"] for idx in inspector.get_indexes("ims_facts")}
        self.assertIn("ix_ims_fact_week", fact_indexes)
        self.assertTrue(self._has_unique(inspector, "ims_facts", "uq_ims_fact_week_period"))

        self.assertTrue(
            self._has_unique(inspector, "representative_matches", "uq_rep_match_ims_name")
        )
        self.assertTrue(self._has_unique(inspector, "product_matches", "uq_product_match_ims_name"))
        self.assertTrue(
            self._has_unique(inspector, "manual_match_queue", "uq_manual_match_entity")
        )

    def _schema_fingerprint(self, inspector):
        return {
            "required_tables": sorted(
                table
                for table in inspector.get_table_names()
                if table
                in {
                    "representative_matches",
                    "product_matches",
                    "manual_match_queue",
                    "import_audit_logs",
                    "ims_uploads",
                    "ims_raw_data",
                    "ims_facts",
                }
            ),
            "ims_uploads_columns": sorted(
                c["name"]
                for c in inspector.get_columns("ims_uploads")
                if c["name"] in {"id", "year", "month", "week_number", "quarter"}
            ),
            "ims_raw_columns": sorted(
                c["name"]
                for c in inspector.get_columns("ims_raw_data")
                if c["name"] in {"id", "year", "month", "week_number", "quarter"}
            ),
            "ims_facts_columns": sorted(
                c["name"]
                for c in inspector.get_columns("ims_facts")
                if c["name"] in {"id", "year", "month", "week_number", "report_type"}
            ),
            "ims_facts_indexes": sorted(
                idx["name"]
                for idx in inspector.get_indexes("ims_facts")
                if idx["name"] in {"ix_ims_fact_week", "uq_ims_fact_week_period"}
            ),
            "ims_fact_week_unique": self._has_unique(
                inspector, "ims_facts", "uq_ims_fact_week_period"
            ),
            "match_uniques": {
                "representative_matches": self._has_unique(
                    inspector, "representative_matches", "uq_rep_match_ims_name"
                ),
                "product_matches": self._has_unique(
                    inspector, "product_matches", "uq_product_match_ims_name"
                ),
                "manual_match_queue": self._has_unique(
                    inspector, "manual_match_queue", "uq_match_queue_entity_name"
                ),
            },
        }

    def test_upgrade_section_is_additive(self):
        migration_text = MIGRATION_FILE.read_text(encoding="utf-8")
        upgrade_section = migration_text.split("def upgrade():", maxsplit=1)[1].split(
            "def downgrade():", maxsplit=1
        )[0]
        self.assertNotIn("drop_table", upgrade_section)
        self.assertNotIn("drop_column", upgrade_section)
        self.assertNotIn("drop_constraint", upgrade_section)

    def test_record_count_migration_upgrade_section_is_additive(self):
        migration_text = MIGRATION_FILE_RECORD_COUNTS.read_text(encoding="utf-8")
        upgrade_section = migration_text.split("def upgrade():", maxsplit=1)[1].split(
            "def downgrade():", maxsplit=1
        )[0]
        self.assertNotIn("drop_table", upgrade_section)
        self.assertNotIn("drop_column", upgrade_section)
        self.assertNotIn("drop_constraint", upgrade_section)

    def test_repair_migration_upgrade_section_is_additive(self):
        migration_text = MIGRATION_FILE_REPAIR.read_text(encoding="utf-8")
        upgrade_section = migration_text.split("def upgrade():", maxsplit=1)[1].split(
            "def downgrade():", maxsplit=1
        )[0]
        self.assertNotIn("drop_table", upgrade_section)
        self.assertNotIn("drop_column", upgrade_section)
        self.assertNotIn("drop_constraint", upgrade_section)

    def _run_migration_safety_flow(self, db_url):
        _create_legacy_schema(db_url)
        app = _build_test_app(db_url)
        engine = sa.create_engine(db_url)

        with engine.begin() as connection:
            before_counts = {
                "users": self._count_rows(connection, "users"),
                "ims_uploads": self._count_rows(connection, "ims_uploads"),
                "ims_raw_data": self._count_rows(connection, "ims_raw_data"),
                "ims_facts": self._count_rows(connection, "ims_facts"),
                "ims_summary": self._count_rows(connection, "ims_summary"),
            }

        with app.app_context():
            upgrade(directory=MIGRATIONS_DIR)
            upgrade(directory=MIGRATIONS_DIR)

        inspector = sa.inspect(engine)
        self._assert_required_schema(inspector)
        self._assert_model_schema_parity(inspector)

        with engine.begin() as connection:
            after_counts = {
                "users": self._count_rows(connection, "users"),
                "ims_uploads": self._count_rows(connection, "ims_uploads"),
                "ims_raw_data": self._count_rows(connection, "ims_raw_data"),
                "ims_facts": self._count_rows(connection, "ims_facts"),
                "ims_summary": self._count_rows(connection, "ims_summary"),
            }
            self.assertEqual(before_counts["users"], after_counts["users"])
            for table_name in (
                "ims_uploads",
                "ims_raw_data",
                "ims_facts",
                "ims_summary",
            ):
                self.assertEqual(0, after_counts[table_name])

            legacy_user_email = connection.execute(
                sa.text("SELECT email FROM users WHERE id = 1")
            ).scalar_one()
            self.assertEqual("legacy.user@example.com", legacy_user_email)

            created_at = datetime(2026, 7, 1, 0, 0, 0)
            connection.execute(
                sa.text(
                    """
                    INSERT INTO ims_uploads
                    (id, file_name, year, month, quarter, uploaded_at)
                    VALUES (1, 'ims-after-reset.xlsx', 2026, 7, 'Q3', :created_at)
                    """
                ),
                {"created_at": created_at},
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO ims_raw_data
                    (id, upload_id, year, month, week_number, quarter, sheet_name, sheet_type,
                     source_row, representative_id, product_id, unit, tl, market_share,
                     value_share, growth, raw_json, created_at)
                    VALUES
                    (2, 1, 2026, 7, 31, 'Q3', 'BRICK SATIS', 'unknown',
                     3, 1, 1, 0, 0, 0, 0, 0, '{}', :created_at)
                    """
                ),
                {"created_at": created_at},
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO ims_facts
                    (id, upload_id, raw_data_id, representative_id, product_id,
                     year, month, week_number, quarter, report_type, unit, tl,
                     market_share, value_share, growth, metrics_json, created_at)
                    VALUES
                    (2, 1, 2, 1, 1, 2026, 7, 31, 'Q3', 'BOX',
                     0, 0, 0, 0, 0, '{}', :created_at)
                    """
                ),
                {"created_at": created_at},
            )

        with self.assertRaises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO ims_raw_data
                        (id, upload_id, year, month, week_number, quarter, sheet_name, sheet_type,
                         source_row, representative_id, product_id, unit, tl, market_share,
                         value_share, growth, raw_json, created_at)
                        VALUES
                        (3, 1, 2026, 7, 31, 'Q3', 'BRICK SATIS', 'unknown',
                         4, 1, 1, 0, 0, 0, 0, 0, '{}', :created_at)
                        """
                    ),
                    {"created_at": datetime(2026, 7, 1, 0, 0, 0)},
                )
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO ims_facts
                        (id, upload_id, raw_data_id, representative_id, product_id,
                         year, month, week_number, quarter, report_type, unit, tl,
                         market_share, value_share, growth, metrics_json, created_at)
                        VALUES
                        (3, 1, 3, 1, 1, 2026, 7, 31, 'Q3', 'BOX',
                         0, 0, 0, 0, 0, '{}', :created_at)
                        """
                    ),
                    {"created_at": datetime(2026, 7, 1, 0, 0, 0)},
                )

        fingerprint = self._schema_fingerprint(inspector)

        with app.app_context():
            downgrade(directory=MIGRATIONS_DIR, revision="base")

        downgraded_inspector = sa.inspect(engine)
        self.assertNotIn("representative_matches", downgraded_inspector.get_table_names())
        self.assertNotIn("product_matches", downgraded_inspector.get_table_names())
        self.assertNotIn("manual_match_queue", downgraded_inspector.get_table_names())
        self.assertNotIn("import_audit_logs", downgraded_inspector.get_table_names())
        self.assertNotIn(
            "week_number",
            [c["name"] for c in downgraded_inspector.get_columns("ims_uploads")],
        )
        self.assertNotIn(
            "week_number",
            [c["name"] for c in downgraded_inspector.get_columns("ims_raw_data")],
        )
        self.assertNotIn(
            "week_number",
            [c["name"] for c in downgraded_inspector.get_columns("ims_facts")],
        )

        with app.app_context():
            upgrade(directory=MIGRATIONS_DIR)

        cycle_inspector = sa.inspect(engine)
        self._assert_required_schema(cycle_inspector)
        with app.app_context():
            db.engine.dispose()
        engine.dispose()
        return fingerprint

    def test_sqlite_migration_safety_and_reentrancy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sqlite_path = Path(temp_dir) / "migration_test.db"
            sqlite_url = f"sqlite:///{sqlite_path}"
            self._run_migration_safety_flow(sqlite_url)

    def test_postgresql_migration_parity_when_available(self):
        postgres_url = os.getenv("TEST_POSTGRES_URL")
        if not postgres_url:
            pytest.skip(
                "Skipping PostgreSQL migration parity test: TEST_POSTGRES_URL is not set."
            )

        try:
            probe_engine = sa.create_engine(postgres_url)
            with probe_engine.connect() as connection:
                connection.execute(sa.text("SELECT 1"))
        except OperationalError as exc:
            pytest.skip(
                "Skipping PostgreSQL migration parity test: TEST_POSTGRES_URL is set "
                f"but database is unreachable ({exc})."
            )
        except Exception as exc:  # pragma: no cover - defensive environment handling
            pytest.skip(
                "Skipping PostgreSQL migration parity test: TEST_POSTGRES_URL is set "
                f"but environment is unavailable ({exc})."
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            sqlite_path = Path(temp_dir) / "migration_test.db"
            sqlite_url = f"sqlite:///{sqlite_path}"
            sqlite_fingerprint = self._run_migration_safety_flow(sqlite_url)
            postgres_fingerprint = self._run_migration_safety_flow(postgres_url)
            self.assertEqual(sqlite_fingerprint, postgres_fingerprint)

    def test_initialize_database_missing_schema_warns_or_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "missing_schema.db"
            db_url = f"sqlite:///{db_path}"

            non_strict_app = _build_test_app(db_url, strict_schema_validation=False)
            with non_strict_app.app_context():
                initialize_database()

            strict_app = _build_test_app(db_url, strict_schema_validation=True)
            with strict_app.app_context():
                with self.assertRaises(RuntimeError):
                    initialize_database()

    def test_sqlite_instance_schema_matches_models_after_upgrade(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sqlite_path = Path(temp_dir) / "ipm.db"
            sqlite_url = f"sqlite:///{sqlite_path}"
            _create_legacy_schema(sqlite_url)
            app = _build_test_app(sqlite_url)

            with app.app_context():
                upgrade(directory=MIGRATIONS_DIR)

            inspection_engine = sa.create_engine(sqlite_url)
            inspector = sa.inspect(inspection_engine)
            model_tables = {
                "ims_uploads": IMSUpload,
                "ims_raw_data": IMSRawData,
                "ims_facts": IMSFact,
                "ims_summary": IMSSummary,
            }
            for table_name, model in model_tables.items():
                model_columns = {column.name for column in model.__table__.columns}
                db_columns = {column["name"] for column in inspector.get_columns(table_name)}
                self.assertEqual(
                    model_columns,
                    db_columns,
                    f"Schema mismatch for {table_name}: model={sorted(model_columns)} db={sorted(db_columns)}",
                )
            inspection_engine.dispose()
            with app.app_context():
                db.engine.dispose()


if __name__ == "__main__":
    unittest.main()
