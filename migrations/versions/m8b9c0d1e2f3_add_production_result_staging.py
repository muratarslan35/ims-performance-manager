"""Add isolated post-sales production result staging.

Revision ID: m8b9c0d1e2f3
Revises: l7a8b9c0d1e2
Create Date: 2026-08-14
"""

from alembic import op
import sqlalchemy as sa


revision = "m8b9c0d1e2f3"
down_revision = "l7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "production_result_uploads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("stored_file_name", sa.String(length=255), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("production_stage", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="PENDING_VALIDATION"),
        sa.Column("uploaded_by", sa.String(length=150), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matched_row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_message", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
        sa.Column("validated_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_hash", name="uq_production_upload_source_hash"),
    )
    op.create_index("ix_production_upload_period", "production_result_uploads", ["year", "month", "production_stage"])
    op.create_table(
        "production_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("upload_id", sa.Integer(), nullable=False),
        sa.Column("representative_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("realization_percent", sa.Float(), nullable=False),
        sa.Column("source_sheet", sa.String(length=150), nullable=True),
        sa.Column("source_row", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["representative_id"], ["representatives.id"]),
        sa.ForeignKeyConstraint(["upload_id"], ["production_result_uploads.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("upload_id", "representative_id", "product_id", name="uq_production_result_row"),
    )
    op.create_index("ix_production_result_rep_product", "production_results", ["representative_id", "product_id"])
    op.create_table(
        "production_representative_totals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("upload_id", sa.Integer(), nullable=False),
        sa.Column("representative_id", sa.Integer(), nullable=False),
        sa.Column("realization_percent", sa.Float(), nullable=False),
        sa.Column("source_sheet", sa.String(length=150), nullable=True),
        sa.Column("source_row", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["representative_id"], ["representatives.id"]),
        sa.ForeignKeyConstraint(["upload_id"], ["production_result_uploads.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("upload_id", "representative_id", name="uq_production_representative_total"),
    )
    op.create_index("ix_production_total_representative", "production_representative_totals", ["representative_id"])


def downgrade():
    op.drop_index("ix_production_total_representative", table_name="production_representative_totals")
    op.drop_table("production_representative_totals")
    op.drop_index("ix_production_result_rep_product", table_name="production_results")
    op.drop_table("production_results")
    op.drop_index("ix_production_upload_period", table_name="production_result_uploads")
    op.drop_table("production_result_uploads")
