"""Keep exact TL and box results from approved production workbooks.

Revision ID: t4i5j6k7l8m9
Revises: s4h5i6j7k8l9
Create Date: 2026-08-23
"""

from alembic import op
import sqlalchemy as sa


revision = "t4i5j6k7l8m9"
down_revision = "s4h5i6j7k8l9"
branch_labels = None
depends_on = None


def upgrade():
    for table_name in ("production_results", "production_representative_totals"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(sa.Column("unit_realization_percent", sa.Float(), nullable=True))
            batch_op.add_column(sa.Column("actual_tl", sa.Float(), nullable=True))
            batch_op.add_column(sa.Column("actual_unit", sa.Float(), nullable=True))


def downgrade():
    for table_name in ("production_representative_totals", "production_results"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_column("actual_unit")
            batch_op.drop_column("actual_tl")
            batch_op.drop_column("unit_realization_percent")
