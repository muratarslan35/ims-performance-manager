"""Align ims_facts schema."""

from alembic import op
import sqlalchemy as sa

revision = "7d6b6e470de7"
down_revision = "3a7f2e1b9c05"
branch_labels = None
depends_on = None


def _insp():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return name in _insp().get_table_names()


def _has_index(table, name):
    if not _has_table(table):
        return False
    return any(i["name"] == name for i in _insp().get_indexes(table))


def _column_names(table):
    if not _has_table(table):
        return set()
    return {c["name"] for c in _insp().get_columns(table)}


def upgrade():

    conn = op.get_bind()

    if _has_table("ims_fact"):

        rows = conn.execute(
            sa.text("SELECT COUNT(*) FROM ims_fact")
        ).scalar()

        if rows and rows > 0:
            raise RuntimeError(
                "Legacy table ims_fact contains data. "
                "Migration aborted."
            )

        op.drop_table("ims_fact")

    if not _has_table("ims_facts"):

        op.create_table(
            "ims_facts",

            sa.Column("id", sa.Integer(), primary_key=True),

            sa.Column(
                "upload_id",
                sa.Integer(),
                sa.ForeignKey("ims_uploads.id"),
                nullable=False,
            ),

            sa.Column(
                "raw_data_id",
                sa.Integer(),
                sa.ForeignKey("ims_raw_data.id"),
                nullable=False,
            ),

            sa.Column(
                "representative_id",
                sa.Integer(),
                sa.ForeignKey("representatives.id"),
                nullable=False,
            ),

            sa.Column(
                "product_id",
                sa.Integer(),
                sa.ForeignKey("products.id"),
                nullable=False,
            ),

            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("month", sa.Integer(), nullable=False),
            sa.Column("week_number", sa.Integer(), nullable=False),
            sa.Column("quarter", sa.String(5), nullable=False),
            sa.Column("report_type", sa.String(50), nullable=False),

            sa.Column("unit", sa.Float(), nullable=False),
            sa.Column("tl", sa.Float(), nullable=False),

            sa.Column("market_share", sa.Float(), nullable=False),
            sa.Column("value_share", sa.Float(), nullable=False),
            sa.Column("growth", sa.Float(), nullable=False),

            sa.Column("metrics_json", sa.Text(), nullable=False),

            sa.Column("created_at", sa.DateTime(), nullable=False),

            sa.UniqueConstraint(
                "raw_data_id",
                name="uq_ims_fact_raw_data",
            ),

            sa.UniqueConstraint(
                "year",
                "month",
                "week_number",
                "representative_id",
                "product_id",
                "report_type",
                name="uq_ims_fact_week_period",
            ),
        )

    if _has_table("ims_facts"):

        if not _has_index(
            "ims_facts",
            "ix_ims_fact_period",
        ):
            op.create_index(
                "ix_ims_fact_period",
                "ims_facts",
                ["year", "month"],
                unique=False,
            )

        if not _has_index(
            "ims_facts",
            "ix_ims_fact_rep_product",
        ):
            op.create_index(
                "ix_ims_fact_rep_product",
                "ims_facts",
                [
                    "representative_id",
                    "product_id",
                ],
                unique=False,
            )

        if not _has_index(
            "ims_facts",
            "ix_ims_fact_week",
        ):
            op.create_index(
                "ix_ims_fact_week",
                "ims_facts",
                [
                    "year",
                    "month",
                    "week_number",
                ],
                unique=False,
            )

    cols = _column_names("ims_uploads")

    if "raw_record_count" not in cols:
        op.add_column(
            "ims_uploads",
            sa.Column(
                "raw_record_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )

    if "fact_record_count" not in cols:
        op.add_column(
            "ims_uploads",
            sa.Column(
                "fact_record_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )

    if "summary_record_count" not in cols:
        op.add_column(
            "ims_uploads",
            sa.Column(
                "summary_record_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )


def downgrade():
    pass

