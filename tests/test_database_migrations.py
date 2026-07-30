import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from flask_migrate import downgrade
from flask_migrate import upgrade

from app import create_app


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = str(REPO_ROOT / "migrations")


def _create_legacy_schema(db_url):
    engine = sa.create_engine(db_url)
    metadata = sa.MetaData()

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

    metadata.create_all(engine)

    with engine.begin() as connection:
        created_at = datetime(2026, 7, 1, 0, 0, 0)
        connection.execute(representatives.insert().values(id=1, rep_name="Rep 1"))
        connection.execute(products.insert().values(id=1, product_name="Product 1"))
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


def _build_test_app(db_url):
    config = type(
        "MigrationTestConfig",
        (),
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": db_url,
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "UPLOAD_FOLDER": Path(tempfile.gettempdir()) / "ims-migration-test-uploads",
            "REPORT_FOLDER": Path(tempfile.gettempdir()) / "ims-migration-test-reports",
            "BACKUP_FOLDER": Path(tempfile.gettempdir()) / "ims-migration-test-backups",
            "LOG_FOLDER": Path(tempfile.gettempdir()) / "ims-migration-test-logs",
        },
    )
    return create_app(config)


class DatabaseMigrationsTestCase(unittest.TestCase):
    def test_upgrade_and_downgrade_preserve_existing_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "migration_test.db"
            db_url = f"sqlite:///{db_path}"
            _create_legacy_schema(db_url)
            app = _build_test_app(db_url)

            with app.app_context():
                upgrade(directory=MIGRATIONS_DIR)

            engine = sa.create_engine(db_url)
            inspector = sa.inspect(engine)

            self.assertIn("representative_matches", inspector.get_table_names())
            self.assertIn("product_matches", inspector.get_table_names())
            self.assertIn("manual_match_queue", inspector.get_table_names())
            self.assertIn("import_audit_logs", inspector.get_table_names())
            self.assertIn("week_number", [c["name"] for c in inspector.get_columns("ims_uploads")])
            self.assertIn("week_number", [c["name"] for c in inspector.get_columns("ims_raw_data")])
            self.assertIn("week_number", [c["name"] for c in inspector.get_columns("ims_facts")])

            indexes = {idx["name"] for idx in inspector.get_indexes("import_audit_logs")}
            self.assertIn("ix_import_audit_upload", indexes)
            self.assertIn("ix_import_audit_period", indexes)

            fact_indexes = {idx["name"] for idx in inspector.get_indexes("ims_facts")}
            self.assertIn("ix_ims_fact_week", fact_indexes)
            self.assertIn("uq_ims_fact_week_period", fact_indexes)

            with engine.begin() as connection:
                uploads_count = connection.execute(sa.text("SELECT COUNT(*) FROM ims_uploads")).scalar_one()
                facts_count = connection.execute(sa.text("SELECT COUNT(*) FROM ims_facts")).scalar_one()

            self.assertEqual(uploads_count, 1)
            self.assertEqual(facts_count, 1)

            with app.app_context():
                downgrade(directory=MIGRATIONS_DIR, revision="base")

            inspector = sa.inspect(engine)
            self.assertNotIn("representative_matches", inspector.get_table_names())
            self.assertNotIn("product_matches", inspector.get_table_names())
            self.assertNotIn("manual_match_queue", inspector.get_table_names())
            self.assertNotIn("import_audit_logs", inspector.get_table_names())
            self.assertNotIn("week_number", [c["name"] for c in inspector.get_columns("ims_uploads")])
            self.assertNotIn("week_number", [c["name"] for c in inspector.get_columns("ims_raw_data")])
            self.assertNotIn("week_number", [c["name"] for c in inspector.get_columns("ims_facts")])


if __name__ == "__main__":
    unittest.main()
