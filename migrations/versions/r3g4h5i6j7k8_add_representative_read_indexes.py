"""Add composite indexes for representative-scoped high-volume reads.

Revision ID: r3g4h5i6j7k8
Revises: q2f3a4b5c6d7
"""

from alembic import op


revision = "r3g4h5i6j7k8"
down_revision = "q2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_competition_upload_metric_flags_subterritory",
        "ims_competition_data",
        ["upload_id", "metric_type", "is_subtotal", "is_grand_total", "subterritory"],
        unique=False,
    )
    op.create_index(
        "ix_ims_raw_upload_sheet_brick",
        "ims_raw_data",
        ["upload_id", "sheet_type", "brick"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_ims_raw_upload_sheet_brick",
        table_name="ims_raw_data",
    )
    op.drop_index(
        "ix_competition_upload_metric_flags_subterritory",
        table_name="ims_competition_data",
    )
