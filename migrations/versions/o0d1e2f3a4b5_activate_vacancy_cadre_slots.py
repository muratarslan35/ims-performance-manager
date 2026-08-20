"""Activate vacancy cadre slots and backfill their organisation profile.

Revision ID: o0d1e2f3a4b5
Revises: n9c0d1e2f3a4
"""

from alembic import op
import sqlalchemy as sa


revision = "o0d1e2f3a4b5"
down_revision = "n9c0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade():
    representatives = sa.table(
        "representatives",
        sa.column("id", sa.Integer()),
        sa.column("rep_code", sa.String()),
        sa.column("city", sa.String()),
        sa.column("territory", sa.String()),
        sa.column("team", sa.String()),
        sa.column("active", sa.Boolean()),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(
            representatives.c.id,
            representatives.c.city,
            representatives.c.territory,
            representatives.c.team,
        ).where(representatives.c.rep_code.like("UNASSIGNED%"))
    ).mappings().all()
    for row in rows:
        values = {"active": True}
        if not (row["team"] or "").strip():
            values["team"] = "TAYFUN-1"
        if not (row["territory"] or "").strip() and (row["city"] or "").strip():
            values["territory"] = row["city"].strip()
        connection.execute(
            representatives.update()
            .where(representatives.c.id == row["id"])
            .values(**values)
        )


def downgrade():
    # The old inactive flag was a business-data defect. Downgrading code must
    # not silently make sales/target-bearing cadre slots inactive again.
    pass
