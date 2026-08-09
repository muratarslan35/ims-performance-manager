"""add period scoped representative brick assignments"""

from alembic import op
import sqlalchemy as sa

revision = "f1a2b3c4d5e6"
down_revision = "e6f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "representative_brick_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("representative_id", sa.Integer(), sa.ForeignKey("representatives.id"), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("quarter", sa.String(length=5)),
        sa.Column("brick", sa.String(length=150), nullable=False),
        sa.Column("territory", sa.String(length=150)),
        sa.Column("city", sa.String(length=100)),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="AUTO"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.UniqueConstraint("year", "month", "brick", name="uq_rep_brick_period"),
    )
    op.create_index("ix_rep_brick_assignment_rep_period", "representative_brick_assignments", ["representative_id", "year", "month"])


def downgrade():
    op.drop_index("ix_rep_brick_assignment_rep_period", table_name="representative_brick_assignments")
    op.drop_table("representative_brick_assignments")
