"""store raw IMS brick dimensions"""

from alembic import op
import sqlalchemy as sa

revision = "g2b3c4d5e6f7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("ims_raw_data")}
    for name, column_type in (("territory", sa.String(length=150)), ("brick", sa.String(length=150)), ("province", sa.String(length=100))):
        if name not in columns:
            op.add_column("ims_raw_data", sa.Column(name, column_type, nullable=True))
    indexes = {index["name"] for index in inspector.get_indexes("ims_raw_data")}
    if "ix_ims_raw_brick_period" not in indexes:
        op.create_index("ix_ims_raw_brick_period", "ims_raw_data", ["year", "month", "brick"], unique=False)


def downgrade():
    op.drop_index("ix_ims_raw_brick_period", table_name="ims_raw_data")
    op.drop_column("ims_raw_data", "province")
    op.drop_column("ims_raw_data", "brick")
    op.drop_column("ims_raw_data", "territory")
