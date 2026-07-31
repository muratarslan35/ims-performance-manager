"""repair ims table column drift

Revision ID: 9f8b1c2d4e6f
Revises: c4f08ef1d2a1
Create Date: 2026-07-31 19:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "9f8b1c2d4e6f"
down_revision = "c4f08ef1d2a1"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name):
    return table_name in set(_inspector().get_table_names())


def _has_column(table_name, column_name):
    if not _has_table(table_name):
        return False
    return any(column["name"] == column_name for column in _inspector().get_columns(table_name))


def _is_sqlite():
    return op.get_bind().dialect.name == "sqlite"


def _ensure_columns(table_name, columns):
    if not _has_table(table_name):
        return

    missing = [column for column in columns if not _has_column(table_name, column.name)]
    if not missing:
        return

    if _is_sqlite():
        with op.batch_alter_table(table_name) as batch_op:
            for column in missing:
                batch_op.add_column(column)
        return

    for column in missing:
        op.add_column(table_name, column)


def upgrade():
    _ensure_columns(
        "representatives",
        [
            sa.Column("rep_code", sa.String(length=30), nullable=True),
            sa.Column("ims_code", sa.String(length=30), nullable=True),
            sa.Column("sap_code", sa.String(length=30), nullable=True),
            sa.Column("region", sa.String(length=100), nullable=True),
            sa.Column("city", sa.String(length=100), nullable=True),
            sa.Column("district", sa.String(length=100), nullable=True),
            sa.Column("territory", sa.String(length=100), nullable=True),
            sa.Column("manager", sa.String(length=120), nullable=True),
            sa.Column("team", sa.String(length=100), nullable=True),
            sa.Column("email", sa.String(length=150), nullable=True),
            sa.Column("phone", sa.String(length=30), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        ],
    )

    _ensure_columns(
        "products",
        [
            sa.Column("product_code", sa.String(length=30), nullable=True),
            sa.Column("ims_name", sa.String(length=200), nullable=True),
            sa.Column("category", sa.String(length=100), nullable=True),
            sa.Column("competitor_group", sa.String(length=100), nullable=True),
            sa.Column("molecule", sa.String(length=100), nullable=True),
            sa.Column("strength", sa.String(length=100), nullable=True),
            sa.Column("dosage_form", sa.String(length=100), nullable=True),
            sa.Column("unit_price", sa.Float(), nullable=False, server_default="0"),
            sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("is_prime_product", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("required_percent", sa.Float(), nullable=False, server_default="0"),
            sa.Column("include_total_tl", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        ],
    )

    _ensure_columns(
        "ims_uploads",
        [
            sa.Column("week_number", sa.Integer(), nullable=True),
            sa.Column("raw_record_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("fact_record_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("summary_record_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("uploaded_by", sa.String(length=120), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("warning_message", sa.Text(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
        ],
    )

    _ensure_columns(
        "ims_raw_data",
        [
            sa.Column("week_number", sa.Integer(), nullable=True),
            sa.Column("representative", sa.String(length=150), nullable=True),
            sa.Column("manager", sa.String(length=150), nullable=True),
            sa.Column("product", sa.String(length=150), nullable=True),
            sa.Column("competitor", sa.String(length=150), nullable=True),
            sa.Column("brick", sa.String(length=150), nullable=True),
            sa.Column("market", sa.String(length=150), nullable=True),
            sa.Column("value_share", sa.Float(), nullable=False, server_default="0"),
        ],
    )

    _ensure_columns(
        "ims_facts",
        [
            sa.Column("week_number", sa.Integer(), nullable=True),
            sa.Column("value_share", sa.Float(), nullable=False, server_default="0"),
        ],
    )

    _ensure_columns(
        "ims_summary",
        [
            sa.Column("value_share", sa.Float(), nullable=False, server_default="0"),
            sa.Column("realization_percent", sa.Float(), nullable=False, server_default="0"),
            sa.Column("prime_percent", sa.Float(), nullable=False, server_default="0"),
            sa.Column("target_unit", sa.Float(), nullable=False, server_default="0"),
            sa.Column("target_tl", sa.Float(), nullable=False, server_default="0"),
            sa.Column("bonus_amount", sa.Float(), nullable=False, server_default="0"),
            sa.Column("rank", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="READY"),
        ],
    )


def downgrade():
    # Additive repair migration; downgrade intentionally no-op to avoid data loss.
    pass
