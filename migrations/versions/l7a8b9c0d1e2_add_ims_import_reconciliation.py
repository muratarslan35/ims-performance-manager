"""Add persisted IMS source reconciliation counters.

Revision ID: l7a8b9c0d1e2
Revises: k6f7a8b9c0d1
Create Date: 2026-08-14
"""

from alembic import op
import sqlalchemy as sa


revision = "l7a8b9c0d1e2"
down_revision = "k6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ims_uploads") as batch_op:
        batch_op.add_column(sa.Column("source_record_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("stored_source_record_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("zero_metric_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("blank_metric_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("invalid_metric_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("excluded_aggregate_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(
            sa.Column("reconciliation_status", sa.String(length=30), nullable=False, server_default="NOT_AVAILABLE")
        )


def downgrade():
    with op.batch_alter_table("ims_uploads") as batch_op:
        batch_op.drop_column("reconciliation_status")
        batch_op.drop_column("excluded_aggregate_count")
        batch_op.drop_column("invalid_metric_count")
        batch_op.drop_column("blank_metric_count")
        batch_op.drop_column("zero_metric_count")
        batch_op.drop_column("stored_source_record_count")
        batch_op.drop_column("source_record_count")
