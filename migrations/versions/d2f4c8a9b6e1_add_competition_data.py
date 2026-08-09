"""Add the persisted competition dataset without changing existing IMS data.

Revision ID: d2f4c8a9b6e1
Revises: c4f08ef1d2a1
"""

from alembic import op
import sqlalchemy as sa


revision = "d2f4c8a9b6e1"
down_revision = "c4f08ef1d2a1"
branch_labels = None
depends_on = None


def _has_table(table_name):
    return table_name in set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    if _has_table("ims_competition_data"):
        return

    op.create_table(
        "ims_competition_data",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("upload_id", sa.Integer(), sa.ForeignKey("ims_uploads.id"), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("week_number", sa.Integer(), nullable=True),
        sa.Column("sheet_name", sa.String(length=150), nullable=False),
        sa.Column("period_type", sa.String(length=30), nullable=False),
        sa.Column("territory", sa.String(length=150), nullable=False),
        sa.Column("subterritory", sa.String(length=150), nullable=False),
        sa.Column("product_group", sa.String(length=200), nullable=False),
        sa.Column("product_name", sa.String(length=200), nullable=False),
        sa.Column("is_company_product", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_competitor", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("metric_type", sa.String(length=30), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("is_subtotal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_grand_total", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint(
            "upload_id", "sheet_name", "period_type", "year", "month", "week_number",
            "territory", "subterritory", "product_group", "product_name", "metric_type",
            name="uq_competition_grain",
        ),
    )
    op.create_index("ix_competition_period", "ims_competition_data", ["year", "month", "week_number"])
    op.create_index("ix_competition_sheet", "ims_competition_data", ["sheet_name"])
    op.create_index("ix_competition_territory", "ims_competition_data", ["territory", "subterritory"])
    op.create_index("ix_ims_competition_data_upload_id", "ims_competition_data", ["upload_id"])


def downgrade():
    pass
