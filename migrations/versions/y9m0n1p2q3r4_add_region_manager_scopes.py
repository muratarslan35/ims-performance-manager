"""add regional manager scope table

Revision ID: y9m0n1p2q3r4
Revises: x8l9m0n1p2q3
"""

from alembic import op
import sqlalchemy as sa

revision = "y9m0n1p2q3r4"
down_revision = "x8l9m0n1p2q3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "region_manager_scopes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("region_code", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_region_manager_scopes_user_id", "region_manager_scopes", ["user_id"], unique=True)
    op.create_index("ix_region_manager_scopes_region_code", "region_manager_scopes", ["region_code"], unique=False)


def downgrade():
    op.drop_index("ix_region_manager_scopes_region_code", table_name="region_manager_scopes")
    op.drop_index("ix_region_manager_scopes_user_id", table_name="region_manager_scopes")
    op.drop_table("region_manager_scopes")
