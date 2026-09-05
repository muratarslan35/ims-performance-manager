"""add persistent manager region snapshots

Revision ID: b2q3s4j5d6e7
Revises: a1p2r3i4c5e6
"""
from alembic import op
import sqlalchemy as sa

revision = "b2q3s4j5d6e7"
down_revision = "a1p2r3i4c5e6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "manager_region_snapshot_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("source_upload_id", sa.Integer(), nullable=False),
        sa.Column("production_upload_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("region_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "year", "month", "source_upload_id", "production_upload_id",
            name="uq_manager_region_snapshot_set_source",
        ),
    )
    op.create_index(
        "ix_manager_region_snapshot_sets_active",
        "manager_region_snapshot_sets",
        ["year", "month", "status", "source_upload_id", "production_upload_id"],
    )
    op.create_table(
        "manager_region_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "set_id", sa.Integer(),
            sa.ForeignKey("manager_region_snapshot_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("region_key", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("set_id", "region_key", name="uq_manager_region_snapshot_region"),
    )
    op.create_index(
        "ix_manager_region_snapshots_lookup",
        "manager_region_snapshots",
        ["set_id", "region_key"],
    )


def downgrade():
    op.drop_index("ix_manager_region_snapshots_lookup", table_name="manager_region_snapshots")
    op.drop_table("manager_region_snapshots")
    op.drop_index("ix_manager_region_snapshot_sets_active", table_name="manager_region_snapshot_sets")
    op.drop_table("manager_region_snapshot_sets")
