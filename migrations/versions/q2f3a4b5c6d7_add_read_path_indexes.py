"""Add composite indexes for high-volume dashboard read paths.

Revision ID: q2f3a4b5c6d7
Revises: p1e2f3a4b5c6
"""

from alembic import op


revision = "q2f3a4b5c6d7"
down_revision = "p1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_ims_raw_upload_sheet_type",
        "ims_raw_data",
        ["upload_id", "sheet_type"],
        unique=False,
    )
    op.create_index(
        "ix_competition_upload_metric_flags",
        "ims_competition_data",
        ["upload_id", "metric_type", "is_subtotal", "is_grand_total"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_competition_upload_metric_flags",
        table_name="ims_competition_data",
    )
    op.drop_index("ix_ims_raw_upload_sheet_type", table_name="ims_raw_data")
