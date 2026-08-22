"""Keep final production workbook target values alongside results.

Revision ID: u5j6k7l8m9n0
Revises: t4i5j6k7l8m9
Create Date: 2026-08-23
"""

from alembic import op
import sqlalchemy as sa


revision = "u5j6k7l8m9n0"
down_revision = "t4i5j6k7l8m9"
branch_labels = None
depends_on = None


def upgrade():
    for table_name in ("production_results", "production_representative_totals"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(sa.Column("target_tl", sa.Float(), nullable=True))
            batch_op.add_column(sa.Column("target_unit", sa.Float(), nullable=True))


def downgrade():
    for table_name in ("production_representative_totals", "production_results"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_column("target_unit")
            batch_op.drop_column("target_tl")
