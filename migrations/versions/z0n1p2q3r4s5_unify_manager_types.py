"""unify manager types

Revision ID: z0n1p2q3r4s5
Revises: y9m0n1p2q3r4
"""

from alembic import op
import sqlalchemy as sa

revision = "z0n1p2q3r4s5"
down_revision = "y9m0n1p2q3r4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("region_manager_scopes") as batch_op:
        batch_op.add_column(
            sa.Column("manager_type", sa.String(length=20), nullable=False, server_default="region")
        )
        batch_op.alter_column(
            "region_code",
            existing_type=sa.String(length=20),
            nullable=True,
        )
        batch_op.create_index("ix_region_manager_scopes_manager_type", ["manager_type"], unique=False)


def downgrade():
    # Functional manager rows have no region and cannot be represented by the old schema.
    op.execute("DELETE FROM region_manager_scopes WHERE manager_type <> 'region' OR region_code IS NULL")
    with op.batch_alter_table("region_manager_scopes") as batch_op:
        batch_op.drop_index("ix_region_manager_scopes_manager_type")
        batch_op.alter_column(
            "region_code",
            existing_type=sa.String(length=20),
            nullable=False,
        )
        batch_op.drop_column("manager_type")
