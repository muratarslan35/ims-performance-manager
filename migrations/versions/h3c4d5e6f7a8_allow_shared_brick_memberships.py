"""allow multiple representatives on the same period brick"""

from alembic import op
import sqlalchemy as sa


revision = "h3c4d5e6f7a8"
down_revision = "g2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite needs batch mode to recreate the table while preserving all
    # existing period assignments and their manual/AUTO source values.
    with op.batch_alter_table("representative_brick_assignments") as batch_op:
        batch_op.drop_constraint("uq_rep_brick_period", type_="unique")
        batch_op.create_unique_constraint(
            "uq_rep_brick_member_period",
            ["year", "month", "brick", "representative_id"],
        )


def downgrade():
    # Downgrade is intentionally conservative: it can only be applied after
    # shared memberships are resolved by an administrator.
    duplicates = op.get_bind().execute(sa.text("""
        SELECT year, month, brick
        FROM representative_brick_assignments
        GROUP BY year, month, brick
        HAVING COUNT(*) > 1
    """)).fetchone()
    if duplicates:
        raise RuntimeError("Shared brick memberships must be resolved before downgrade.")
    with op.batch_alter_table("representative_brick_assignments") as batch_op:
        batch_op.drop_constraint("uq_rep_brick_member_period", type_="unique")
        batch_op.create_unique_constraint("uq_rep_brick_period", ["year", "month", "brick"])
