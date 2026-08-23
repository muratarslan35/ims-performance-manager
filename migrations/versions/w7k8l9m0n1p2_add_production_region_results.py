"""Store authoritative region totals from production workbooks.

Revision ID: w7k8l9m0n1p2
Revises: v6k7l8m9n0p1
Create Date: 2026-08-23
"""

from alembic import op
import sqlalchemy as sa


revision = "w7k8l9m0n1p2"
down_revision = "v6k7l8m9n0p1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "production_region_totals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("upload_id", sa.Integer(), nullable=False),
        sa.Column("region_code", sa.String(length=20), nullable=False),
        sa.Column("target_tl", sa.Float(), nullable=False), sa.Column("target_unit", sa.Float(), nullable=False),
        sa.Column("actual_tl", sa.Float(), nullable=False), sa.Column("actual_unit", sa.Float(), nullable=False),
        sa.Column("realization_percent", sa.Float(), nullable=False), sa.Column("unit_realization_percent", sa.Float(), nullable=False),
        sa.Column("source_sheet", sa.String(length=150)), sa.Column("source_row", sa.Integer()),
        sa.ForeignKeyConstraint(["upload_id"], ["production_result_uploads.id"]),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("upload_id", "region_code", name="uq_production_region_total"),
    )
    op.create_index("ix_production_region_total_upload_region", "production_region_totals", ["upload_id", "region_code"])
    op.create_table(
        "production_region_product_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("upload_id", sa.Integer(), nullable=False), sa.Column("region_code", sa.String(length=20), nullable=False), sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("target_tl", sa.Float(), nullable=False), sa.Column("target_unit", sa.Float(), nullable=False),
        sa.Column("actual_tl", sa.Float(), nullable=False), sa.Column("actual_unit", sa.Float(), nullable=False),
        sa.Column("realization_percent", sa.Float(), nullable=False), sa.Column("unit_realization_percent", sa.Float(), nullable=False),
        sa.Column("source_sheet", sa.String(length=150)), sa.Column("source_row", sa.Integer()),
        sa.ForeignKeyConstraint(["upload_id"], ["production_result_uploads.id"]), sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("upload_id", "region_code", "product_id", name="uq_production_region_product"),
    )
    op.create_index("ix_production_region_product_upload_region", "production_region_product_results", ["upload_id", "region_code"])


def downgrade():
    op.drop_index("ix_production_region_product_upload_region", table_name="production_region_product_results")
    op.drop_table("production_region_product_results")
    op.drop_index("ix_production_region_total_upload_region", table_name="production_region_totals")
    op.drop_table("production_region_totals")
