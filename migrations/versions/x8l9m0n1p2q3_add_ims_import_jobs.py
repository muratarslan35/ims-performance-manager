"""add persistent IMS import jobs

Revision ID: x8l9m0n1p2q3
Revises: w7k8l9m0n1p2
"""
from alembic import op
import sqlalchemy as sa


revision = "x8l9m0n1p2q3"
down_revision = "w7k8l9m0n1p2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ims_import_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("stored_file_name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("clear_before_import", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("uploaded_by", sa.String(length=150), nullable=False),
        sa.Column("ims_upload_id", sa.Integer(), sa.ForeignKey("ims_uploads.id"), nullable=True),
        sa.Column("queued_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
    )
    op.create_index("ix_ims_import_jobs_claim", "ims_import_jobs", ["status", "queued_at", "id"])
    op.create_index("ix_ims_import_jobs_user", "ims_import_jobs", ["uploaded_by", "queued_at"])


def downgrade():
    op.drop_index("ix_ims_import_jobs_user", table_name="ims_import_jobs")
    op.drop_index("ix_ims_import_jobs_claim", table_name="ims_import_jobs")
    op.drop_table("ims_import_jobs")
