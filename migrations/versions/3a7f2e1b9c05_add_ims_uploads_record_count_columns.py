"""add ims_uploads record count columns

Revision ID: 3a7f2e1b9c05
Revises: e7e561790e74
Create Date: 2026-07-30 17:00:00.000000

Root cause: ims_uploads tables created before Alembic (or via an early
schema path) are missing raw_record_count, fact_record_count, and
summary_record_count.  The initial migration (ec4e43ee9481) skips the
entire create_table block when the table already exists, so these columns
were never added to pre-existing schemas.  This migration fills that gap
additively and is safe to run against schemas that already have the columns.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3a7f2e1b9c05'
down_revision = 'e7e561790e74'
branch_labels = None
depends_on = None

_RECORD_COUNT_COLUMNS = (
    "raw_record_count",
    "fact_record_count",
    "summary_record_count",
)


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

    missing = [col for col in _RECORD_COUNT_COLUMNS if not _has_column("ims_uploads", col)]
    if not missing:
        return

    if _is_sqlite():
        with op.batch_alter_table("ims_uploads") as batch_op:
            for col in missing:
                batch_op.add_column(
                    sa.Column(col, sa.Integer(), nullable=False, server_default="0")
                )
    else:
        for col in missing:
            op.add_column(
                "ims_uploads",
                sa.Column(col, sa.Integer(), nullable=False, server_default="0"),
            )


def downgrade():
    # These columns belong to the original intended schema.  Dropping them
    # would cause data loss for any import records already written.
    # Downgrade is intentionally a no-op; a DBA manual action is required
    # if removal is ever needed.
    pass
