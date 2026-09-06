"""add persistent representative snapshots

Revision ID: a2b3c4d5e6f7
Revises: z0n1p2q3r4s5
"""
from alembic import op
import sqlalchemy as sa

revision = "a2b3c4d5e6f7"
down_revision = "z0n1p2q3r4s5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "representative_snapshot_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("source_upload_id", sa.Integer(), nullable=False),
        sa.Column("production_upload_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("representative_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_representative_snapshot_sets_source",
        "representative_snapshot_sets",
        ["year", "month", "source_upload_id", "production_upload_id", "status"],
        unique=False,
    )
    op.create_table(
        "representative_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("set_id", sa.Integer(), nullable=False),
        sa.Column("representative_id", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["set_id"], ["representative_snapshot_sets.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "set_id", "representative_id", name="uq_representative_snapshot_member"
        ),
    )
    op.create_index(
        "ix_representative_snapshots_lookup",
        "representative_snapshots",
        ["set_id", "representative_id"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_representative_snapshots_lookup", table_name="representative_snapshots")
    op.drop_table("representative_snapshots")
    op.drop_index("ix_representative_snapshot_sets_source", table_name="representative_snapshot_sets")
    op.drop_table("representative_snapshot_sets")
