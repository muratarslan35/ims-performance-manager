"""repair ims_uploads schema drift

Revision ID: 3a7f2e1b9c05
Revises: e7e561790e74
Create Date: 2026-07-30 17:00:00.000000

Root cause: legacy SQLite ims_uploads tables can predate Alembic (or come
from early schema paths) and therefore miss columns that the current
SQLAlchemy model expects. The initial migration (ec4e43ee9481) skips the
entire create_table block when ims_uploads already exists, so later upgrades
never repaired those missing fields. This migration fills that gap
additively and is safe to run against schemas that already have some or all
of the columns.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3a7f2e1b9c05'
down_revision = 'e7e561790e74'
branch_labels = None
depends_on = None

def _ims_upload_column_factories():
    return {
        "week_number": lambda: sa.Column("week_number", sa.Integer(), nullable=True),
        "sheet_count": lambda: sa.Column(
            "sheet_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        "raw_record_count": lambda: sa.Column(
            "raw_record_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        "fact_record_count": lambda: sa.Column(
            "fact_record_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        "summary_record_count": lambda: sa.Column(
            "summary_record_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        "status": lambda: sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'PROCESSING'"),
        ),
        "processing_time": lambda: sa.Column(
            "processing_time",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        "uploaded_by": lambda: sa.Column("uploaded_by", sa.String(length=120), nullable=True),
        "error_message": lambda: sa.Column("error_message", sa.Text(), nullable=True),
        "warning_message": lambda: sa.Column("warning_message", sa.Text(), nullable=True),
        "uploaded_at": lambda: sa.Column(
            "uploaded_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        "completed_at": lambda: sa.Column("completed_at", sa.DateTime(), nullable=True),
    }


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name):
    return table_name in set(_inspector().get_table_names())


def _has_column(table_name, column_name):
    if not _has_table(table_name):
        return False
    columns = _inspector().get_columns(table_name)
    return any(col["name"] == column_name for col in columns)


def _is_sqlite():
    return op.get_bind().dialect.name == "sqlite"


def upgrade():
    if not _has_table("ims_uploads"):
        return

    column_factories = _ims_upload_column_factories()
    missing = [col for col in column_factories if not _has_column("ims_uploads", col)]
    if not missing:
        return

    if _is_sqlite():
        with op.batch_alter_table("ims_uploads") as batch_op:
            for col in missing:
                batch_op.add_column(column_factories[col]())
    else:
        for col in missing:
            op.add_column("ims_uploads", column_factories[col]())


def downgrade():
    # These columns belong to the original intended schema.  Dropping them
    # would cause data loss for any import records already written.
    # Downgrade is intentionally a no-op; a DBA manual action is required
    # if removal is ever needed.
    pass
