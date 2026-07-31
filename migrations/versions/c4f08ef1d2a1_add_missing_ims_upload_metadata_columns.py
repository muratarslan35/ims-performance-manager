"""add missing ims_uploads metadata columns

Revision ID: c4f08ef1d2a1
Revises: b19e4f6a2d10
Create Date: 2026-07-31 16:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c4f08ef1d2a1"
down_revision = "b19e4f6a2d10"
branch_labels = None
depends_on = None


def _column_names(table_name):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    columns = _column_names("ims_uploads")

    if "uploaded_by" not in columns:
        op.add_column("ims_uploads", sa.Column("uploaded_by", sa.String(length=120), nullable=True))

    if "error_message" not in columns:
        op.add_column("ims_uploads", sa.Column("error_message", sa.Text(), nullable=True))

    if "warning_message" not in columns:
        op.add_column("ims_uploads", sa.Column("warning_message", sa.Text(), nullable=True))

    if "completed_at" not in columns:
        op.add_column("ims_uploads", sa.Column("completed_at", sa.DateTime(), nullable=True))

    raw_columns = _column_names("ims_raw_data")
    for column_name in (
        "representative",
        "manager",
        "product",
        "competitor",
        "brick",
        "market",
    ):
        if column_name not in raw_columns:
            op.add_column("ims_raw_data", sa.Column(column_name, sa.String(length=150), nullable=True))


def downgrade():
    raw_columns = _column_names("ims_raw_data")
    for column_name in ("market", "brick", "competitor", "product", "manager", "representative"):
        if column_name in raw_columns:
            with op.batch_alter_table("ims_raw_data") as batch_op:
                batch_op.drop_column(column_name)

    columns = _column_names("ims_uploads")

    if "completed_at" in columns:
        with op.batch_alter_table("ims_uploads") as batch_op:
            batch_op.drop_column("completed_at")

    if "warning_message" in columns:
        with op.batch_alter_table("ims_uploads") as batch_op:
            batch_op.drop_column("warning_message")

    if "error_message" in columns:
        with op.batch_alter_table("ims_uploads") as batch_op:
            batch_op.drop_column("error_message")

    if "uploaded_by" in columns:
        with op.batch_alter_table("ims_uploads") as batch_op:
            batch_op.drop_column("uploaded_by")
