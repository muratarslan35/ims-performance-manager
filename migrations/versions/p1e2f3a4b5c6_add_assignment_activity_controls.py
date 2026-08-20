"""Add period assignment activity controls.

Revision ID: p1e2f3a4b5c6
Revises: o0d1e2f3a4b5
"""

from alembic import op
import sqlalchemy as sa


revision = "p1e2f3a4b5c6"
down_revision = "o0d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("representative_brick_assignments") as batch_op:
        batch_op.add_column(sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("inactive_reason", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("deactivated_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("representative_brick_assignments") as batch_op:
        batch_op.alter_column("active", server_default=None)


def downgrade():
    with op.batch_alter_table("representative_brick_assignments") as batch_op:
        batch_op.drop_column("deactivated_at")
        batch_op.drop_column("inactive_reason")
        batch_op.drop_column("active")
