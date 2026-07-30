"""harden schema migrations

Revision ID: e7e561790e74
Revises: 
Create Date: 2026-07-30 05:03:27.936295

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e7e561790e74'
down_revision = None
branch_labels = None
depends_on = None


def _dialect_name():
    return op.get_bind().dialect.name


def _is_sqlite():
    return _dialect_name() == "sqlite"


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name):
    return table_name in set(_inspector().get_table_names())


def _has_column(table_name, column_name):
    if not _has_table(table_name):
        return False
    columns = _inspector().get_columns(table_name)
    return any(column["name"] == column_name for column in columns)


def _has_index(table_name, index_name):
    if not _has_table(table_name):
        return False
    indexes = _inspector().get_indexes(table_name)
    return any(index["name"] == index_name for index in indexes)


def _has_unique_constraint(table_name, constraint_name):
    if not _has_table(table_name):
        return False
    constraints = _inspector().get_unique_constraints(table_name)
    return any(constraint.get("name") == constraint_name for constraint in constraints)


def _create_unique_period_guard():
    if not _has_table("ims_facts"):
        return

    if _is_sqlite():
        if not _has_index("ims_facts", "uq_ims_fact_week_period"):
            op.create_index(
                "uq_ims_fact_week_period",
                "ims_facts",
                ["year", "week_number", "representative_id", "product_id", "report_type"],
                unique=True,
            )
        return

    if not _has_unique_constraint("ims_facts", "uq_ims_fact_week_period"):
        op.create_unique_constraint(
            "uq_ims_fact_week_period",
            "ims_facts",
            ["year", "week_number", "representative_id", "product_id", "report_type"],
        )


def upgrade():
    if not _has_table("representative_matches"):
        op.create_table(
            "representative_matches",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("ims_name", sa.String(length=200), nullable=False),
            sa.Column("representative_id", sa.Integer(), nullable=False),
            sa.Column("match_method", sa.String(length=50), nullable=False),
            sa.Column("match_score", sa.Float(), nullable=False),
            sa.Column("created_by", sa.String(length=150), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["representative_id"],
                ["representatives.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("ims_name", name="uq_rep_match_ims_name"),
        )
    if _has_table("representative_matches") and not _has_index(
        "representative_matches",
        "ix_rep_match_rep_id",
    ):
        op.create_index(
            "ix_rep_match_rep_id",
            "representative_matches",
            ["representative_id"],
            unique=False,
        )

    if not _has_table("product_matches"):
        op.create_table(
            "product_matches",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("ims_name", sa.String(length=200), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("match_method", sa.String(length=50), nullable=False),
            sa.Column("match_score", sa.Float(), nullable=False),
            sa.Column("created_by", sa.String(length=150), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("ims_name", name="uq_product_match_ims_name"),
        )
    if _has_table("product_matches") and not _has_index(
        "product_matches",
        "ix_product_match_product_id",
    ):
        op.create_index(
            "ix_product_match_product_id",
            "product_matches",
            ["product_id"],
            unique=False,
        )

    if not _has_table("manual_match_queue"):
        op.create_table(
            "manual_match_queue",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("entity_type", sa.String(length=30), nullable=False),
            sa.Column("ims_name", sa.String(length=200), nullable=False),
            sa.Column("upload_id", sa.Integer(), nullable=True),
            sa.Column("best_candidate", sa.String(length=200), nullable=True),
            sa.Column("best_score", sa.Float(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("resolved_by", sa.String(length=150), nullable=True),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["upload_id"], ["ims_uploads.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "entity_type",
                "ims_name",
                name="uq_match_queue_entity_name",
            ),
        )
    if _has_table("manual_match_queue") and not _has_index(
        "manual_match_queue",
        "ix_match_queue_status",
    ):
        op.create_index(
            "ix_match_queue_status",
            "manual_match_queue",
            ["status"],
            unique=False,
        )

    if not _has_table("import_audit_logs"):
        op.create_table(
            "import_audit_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("upload_id", sa.Integer(), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("month", sa.Integer(), nullable=False),
            sa.Column("week_number", sa.Integer(), nullable=True),
            sa.Column("uploaded_by", sa.String(length=150), nullable=True),
            sa.Column("uploaded_at", sa.DateTime(), nullable=False),
            sa.Column("rows_inserted", sa.Integer(), nullable=False),
            sa.Column("rows_updated", sa.Integer(), nullable=False),
            sa.Column("rows_skipped", sa.Integer(), nullable=False),
            sa.Column("rows_unmatched", sa.Integer(), nullable=False),
            sa.Column("rows_error", sa.Integer(), nullable=False),
            sa.Column("queued_for_manual", sa.Integer(), nullable=False),
            sa.Column("processing_time", sa.Float(), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["upload_id"], ["ims_uploads.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if _has_table("import_audit_logs") and not _has_index(
        "import_audit_logs",
        "ix_import_audit_upload",
    ):
        op.create_index(
            "ix_import_audit_upload",
            "import_audit_logs",
            ["upload_id"],
            unique=False,
        )
    if _has_table("import_audit_logs") and not _has_index(
        "import_audit_logs",
        "ix_import_audit_period",
    ):
        op.create_index(
            "ix_import_audit_period",
            "import_audit_logs",
            ["year", "week_number"],
            unique=False,
        )

    if _has_table("ims_uploads") and not _has_column("ims_uploads", "week_number"):
        op.add_column("ims_uploads", sa.Column("week_number", sa.Integer(), nullable=True))

    if _has_table("ims_raw_data") and not _has_column("ims_raw_data", "week_number"):
        op.add_column("ims_raw_data", sa.Column("week_number", sa.Integer(), nullable=True))

    if _has_table("ims_facts") and not _has_column("ims_facts", "week_number"):
        op.add_column("ims_facts", sa.Column("week_number", sa.Integer(), nullable=True))

    if _has_table("ims_facts") and not _has_index("ims_facts", "ix_ims_fact_week"):
        op.create_index(
            "ix_ims_fact_week",
            "ims_facts",
            ["year", "week_number"],
            unique=False,
        )

    _create_unique_period_guard()


def downgrade():
    # Downgrade is intentionally destructive for this revision:
    # - week_number data stored after upgrade will be removed.
    # - matching/audit tables introduced by this revision will be dropped.
    if _has_table("ims_facts"):
        if _is_sqlite():
            if _has_index("ims_facts", "uq_ims_fact_week_period"):
                op.drop_index("uq_ims_fact_week_period", table_name="ims_facts")
        elif _has_unique_constraint("ims_facts", "uq_ims_fact_week_period"):
            op.drop_constraint("uq_ims_fact_week_period", "ims_facts", type_="unique")

        if _has_index("ims_facts", "ix_ims_fact_week"):
            op.drop_index("ix_ims_fact_week", table_name="ims_facts")

        if _has_column("ims_facts", "week_number"):
            if _is_sqlite():
                with op.batch_alter_table("ims_facts") as batch_op:
                    batch_op.drop_column("week_number")
            else:
                op.drop_column("ims_facts", "week_number")

    if _has_table("ims_raw_data") and _has_column("ims_raw_data", "week_number"):
        if _is_sqlite():
            with op.batch_alter_table("ims_raw_data") as batch_op:
                batch_op.drop_column("week_number")
        else:
            op.drop_column("ims_raw_data", "week_number")

    if _has_table("ims_uploads") and _has_column("ims_uploads", "week_number"):
        if _is_sqlite():
            with op.batch_alter_table("ims_uploads") as batch_op:
                batch_op.drop_column("week_number")
        else:
            op.drop_column("ims_uploads", "week_number")

    if _has_table("import_audit_logs"):
        if _has_index("import_audit_logs", "ix_import_audit_period"):
            op.drop_index("ix_import_audit_period", table_name="import_audit_logs")
        if _has_index("import_audit_logs", "ix_import_audit_upload"):
            op.drop_index("ix_import_audit_upload", table_name="import_audit_logs")
        op.drop_table("import_audit_logs")

    if _has_table("manual_match_queue"):
        if _has_index("manual_match_queue", "ix_match_queue_status"):
            op.drop_index("ix_match_queue_status", table_name="manual_match_queue")
        op.drop_table("manual_match_queue")

    if _has_table("product_matches"):
        if _has_index("product_matches", "ix_product_match_product_id"):
            op.drop_index("ix_product_match_product_id", table_name="product_matches")
        op.drop_table("product_matches")

    if _has_table("representative_matches"):
        if _has_index("representative_matches", "ix_rep_match_rep_id"):
            op.drop_index("ix_rep_match_rep_id", table_name="representative_matches")
        op.drop_table("representative_matches")
