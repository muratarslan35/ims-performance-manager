"""Add period-scoped product unit price history.

Revision ID: a1p2r3i4c5e6
Revises: z0n1p2q3r4s5
"""
from alembic import op
import sqlalchemy as sa

revision = "a1p2r3i4c5e6"
down_revision = "z0n1p2q3r4s5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "product_unit_price_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("effective_year", sa.Integer(), nullable=False),
        sa.Column("effective_month", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("product_id", "effective_year", "effective_month", name="uq_product_price_period"),
    )
    op.create_index(
        "ix_product_price_history_lookup",
        "product_unit_price_history",
        ["product_id", "effective_year", "effective_month"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_product_price_history_lookup", table_name="product_unit_price_history")
    op.drop_table("product_unit_price_history")
