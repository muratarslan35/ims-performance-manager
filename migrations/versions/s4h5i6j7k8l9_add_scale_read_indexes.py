"""Add composite indexes for projected 50-upload read paths.

Revision ID: s4h5i6j7k8l9
Revises: r3g4h5i6j7k8
"""

from alembic import op


revision = "s4h5i6j7k8l9"
down_revision = "r3g4h5i6j7k8"
branch_labels = None
depends_on = None


def upgrade():
    # Previous-IMS delta and acceptance both read facts by upload and then
    # aggregate by representative/product.  Without this index those reads
    # become table scans as weekly history grows.
    op.create_index(
        "ix_ims_fact_upload_rep_product",
        "ims_facts",
        ["upload_id", "representative_id", "product_id"],
        unique=False,
    )
    # Representative 1/3/6/12-month views lead with representative_id and then
    # bound the period.  The existing period-first index serves national reads;
    # this complementary index keeps representative history bounded.
    op.create_index(
        "ix_ims_summary_rep_period_product",
        "ims_summary",
        ["representative_id", "year", "month", "product_id"],
        unique=False,
    )
    op.create_index(
        "ix_target_rep_period_product",
        "targets",
        ["representative_id", "year", "month", "product_id"],
        unique=False,
    )
    # Upload history remains small, but this removes sorting/scanning from the
    # hot latest-completed / previous-upload lookup used throughout the app.
    op.create_index(
        "ix_ims_upload_status_period",
        "ims_uploads",
        ["status", "year", "month", "week_number", "id"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_ims_upload_status_period", table_name="ims_uploads")
    op.drop_index("ix_target_rep_period_product", table_name="targets")
    op.drop_index("ix_ims_summary_rep_period_product", table_name="ims_summary")
    op.drop_index("ix_ims_fact_upload_rep_product", table_name="ims_facts")
