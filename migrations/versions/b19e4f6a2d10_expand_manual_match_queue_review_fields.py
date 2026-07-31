"""expand manual_match_queue review fields

Revision ID: b19e4f6a2d10
Revises: 7d6b6e470de7
Create Date: 2026-07-31 16:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b19e4f6a2d10"
down_revision = "7d6b6e470de7"
branch_labels = None
depends_on = None

_TABLE = "manual_match_queue"
_ADDITIVE_COLUMNS = (
    ("source_value", sa.String(length=200), True, None),
    ("normalized_value", sa.String(length=200), True, None),
    ("import_id", sa.Integer(), True, None),
    ("worksheet", sa.String(length=150), True, None),
    ("row_number", sa.Integer(), True, None),
    ("confidence_score", sa.Float(), False, "0"),
    ("suggested_match", sa.String(length=200), True, None),
    ("reason", sa.String(length=100), True, None),
)


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return name in set(_inspector().get_table_names())


def _has_column(table_name, column_name):
    if not _has_table(table_name):
        return False
    return any(column["name"] == column_name for column in _inspector().get_columns(table_name))


def _is_sqlite():
    return op.get_bind().dialect.name == "sqlite"


def upgrade():
    if not _has_table(_TABLE):
        return

    missing_columns = [column for column in _ADDITIVE_COLUMNS if not _has_column(_TABLE, column[0])]
    if not missing_columns:
        return

    if _is_sqlite():
        with op.batch_alter_table(_TABLE) as batch_op:
            for name, column_type, nullable, default in missing_columns:
                batch_op.add_column(
                    sa.Column(name, column_type, nullable=nullable, server_default=default)
                )
    else:
        for name, column_type, nullable, default in missing_columns:
            op.add_column(
                _TABLE,
                sa.Column(name, column_type, nullable=nullable, server_default=default),
            )

    if _has_column(_TABLE, "source_value"):
        op.execute(
            sa.text(
                "UPDATE manual_match_queue SET source_value = ims_name "
                "WHERE source_value IS NULL OR source_value = ''"
            )
        )
    if _has_column(_TABLE, "normalized_value"):
        op.execute(
            sa.text(
                "UPDATE manual_match_queue SET normalized_value = UPPER(TRIM(ims_name)) "
                "WHERE normalized_value IS NULL OR normalized_value = ''"
            )
        )
    if _has_column(_TABLE, "import_id"):
        op.execute(
            sa.text("UPDATE manual_match_queue SET import_id = upload_id WHERE import_id IS NULL")
        )
    if _has_column(_TABLE, "confidence_score"):
        op.execute(
            sa.text(
                "UPDATE manual_match_queue SET confidence_score = COALESCE(best_score, 0) "
                "WHERE confidence_score IS NULL OR confidence_score = 0"
            )
        )
    if _has_column(_TABLE, "suggested_match"):
        op.execute(
            sa.text(
                "UPDATE manual_match_queue SET suggested_match = best_candidate "
                "WHERE suggested_match IS NULL OR suggested_match = ''"
            )
        )


def downgrade():
    # Additive schema hardening migration: downgrade is intentionally no-op to avoid data loss.
    pass
