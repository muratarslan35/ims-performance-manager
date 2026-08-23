"""Store authoritative NATIONAL production totals.

Revision ID: v6k7l8m9n0p1
Revises: u5j6k7l8m9n0
Create Date: 2026-08-23
"""

from alembic import op
import sqlalchemy as sa


revision = "v6k7l8m9n0p1"
down_revision = "u5j6k7l8m9n0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "production_national_totals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("upload_id", sa.Integer(), nullable=False),
        sa.Column("target_tl", sa.Float(), nullable=False),
        sa.Column("target_unit", sa.Float(), nullable=False),
        sa.Column("actual_tl", sa.Float(), nullable=False),
        sa.Column("actual_unit", sa.Float(), nullable=False),
        sa.Column("realization_percent", sa.Float(), nullable=False),
        sa.Column("unit_realization_percent", sa.Float(), nullable=False),
        sa.Column("source_sheet", sa.String(length=150)),
        sa.Column("source_row", sa.Integer()),
        sa.ForeignKeyConstraint(["upload_id"], ["production_result_uploads.id"]),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("upload_id"),
    )
    op.create_table(
        "production_national_product_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("upload_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("actual_tl", sa.Float(), nullable=False),
        sa.Column("actual_unit", sa.Float(), nullable=False),
        sa.Column("realization_percent", sa.Float(), nullable=False),
        sa.Column("unit_realization_percent", sa.Float(), nullable=False),
        sa.Column("source_sheet", sa.String(length=150)),
        sa.Column("source_row", sa.Integer()),
        sa.ForeignKeyConstraint(["upload_id"], ["production_result_uploads.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("upload_id", "product_id", name="uq_production_national_product"),
    )


def downgrade():
    op.drop_table("production_national_product_results")
    op.drop_table("production_national_totals")
