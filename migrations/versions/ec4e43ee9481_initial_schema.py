"""initial schema

Revision ID: ec4e43ee9481
Revises: 
Create Date: 2026-07-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ec4e43ee9481'
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


def upgrade():
    # All create_table calls are idempotent: pre-existing tables from a
    # legacy (pre-Alembic) schema are left untouched. This is intentional
    # because a production database stamped with ec4e43ee9481 already has
    # these tables; running upgrade on a legacy database (no alembic_version)
    # will also skip tables that were created outside Alembic.

    if not _has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("full_name", sa.String(length=150), nullable=False),
            sa.Column("email", sa.String(length=150), nullable=False),
            sa.Column("password", sa.String(length=255), nullable=False),
            sa.Column("phone", sa.String(length=30), nullable=True),
            sa.Column("role", sa.String(length=50), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column("last_login", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("email"),
        )

    if not _has_table("representatives"):
        op.create_table(
            "representatives",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("rep_code", sa.String(length=30), nullable=True),
            sa.Column("ims_code", sa.String(length=30), nullable=True),
            sa.Column("sap_code", sa.String(length=30), nullable=True),
            sa.Column("rep_name", sa.String(length=150), nullable=False),
            sa.Column("region", sa.String(length=100), nullable=True),
            sa.Column("city", sa.String(length=100), nullable=True),
            sa.Column("district", sa.String(length=100), nullable=True),
            sa.Column("territory", sa.String(length=100), nullable=True),
            sa.Column("manager", sa.String(length=120), nullable=True),
            sa.Column("team", sa.String(length=100), nullable=True),
            sa.Column("email", sa.String(length=150), nullable=True),
            sa.Column("phone", sa.String(length=30), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("rep_code"),
        )

    if not _has_table("products"):
        op.create_table(
            "products",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("product_code", sa.String(length=30), nullable=True),
            sa.Column("product_name", sa.String(length=150), nullable=False),
            sa.Column("ims_name", sa.String(length=200), nullable=True),
            sa.Column("category", sa.String(length=100), nullable=True),
            sa.Column("competitor_group", sa.String(length=100), nullable=True),
            sa.Column("molecule", sa.String(length=100), nullable=True),
            sa.Column("strength", sa.String(length=100), nullable=True),
            sa.Column("dosage_form", sa.String(length=100), nullable=True),
            sa.Column("unit_price", sa.Float(), nullable=False),
            sa.Column("display_order", sa.Integer(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("is_prime_product", sa.Boolean(), nullable=False),
            sa.Column("required_percent", sa.Float(), nullable=False),
            sa.Column("include_total_tl", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("product_code"),
        )

    if not _has_table("settings"):
        op.create_table(
            "settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("setting_key", sa.String(length=120), nullable=False),
            sa.Column("setting_value", sa.String(length=255), nullable=False),
            sa.Column("description", sa.String(length=255), nullable=True),
            sa.Column("category", sa.String(length=100), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("setting_key"),
        )

    if not _has_table("audit_logs"):
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("username", sa.String(length=150), nullable=True),
            sa.Column("module", sa.String(length=100), nullable=True),
            sa.Column("action", sa.String(length=255), nullable=True),
            sa.Column("ip_address", sa.String(length=50), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_table("prime_rules"):
        op.create_table(
            "prime_rules",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("required_percent", sa.Integer(), nullable=False),
            sa.Column("include_in_prime", sa.Boolean(), nullable=False),
            sa.Column("include_in_total_tl", sa.Boolean(), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column("valid_from", sa.Date(), nullable=False),
            sa.Column("valid_to", sa.Date(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_table("targets"):
        op.create_table(
            "targets",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("month", sa.Integer(), nullable=False),
            sa.Column("quarter", sa.String(length=5), nullable=False),
            sa.Column("representative_id", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("unit_target", sa.Float(), nullable=False),
            sa.Column("tl_target", sa.Float(), nullable=False),
            sa.Column("unit_realization", sa.Float(), nullable=False),
            sa.Column("tl_realization", sa.Float(), nullable=False),
            sa.Column("realization_percent", sa.Float(), nullable=False),
            sa.Column("prime_percent", sa.Float(), nullable=False),
            sa.Column("bonus_amount", sa.Float(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
            sa.ForeignKeyConstraint(["representative_id"], ["representatives.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "year", "month", "representative_id", "product_id",
                name="uq_target_period",
            ),
        )

    if not _has_table("product_aliases"):
        op.create_table(
            "product_aliases",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("alias_name", sa.String(length=200), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("product_id", "alias_name", name="uq_product_alias"),
        )

    if not _has_table("representative_aliases"):
        op.create_table(
            "representative_aliases",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("representative_id", sa.Integer(), nullable=False),
            sa.Column("alias_name", sa.String(length=200), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["representative_id"], ["representatives.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "representative_id", "alias_name", name="uq_representative_alias"
            ),
        )

    if not _has_table("recovery_summary"):
        op.create_table(
            "recovery_summary",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("representative_id", sa.Integer(), nullable=True),
            sa.Column("product_id", sa.Integer(), nullable=True),
            sa.Column("year", sa.Integer(), nullable=True),
            sa.Column("quarter", sa.Integer(), nullable=True),
            sa.Column("remaining_box", sa.Float(), nullable=False),
            sa.Column("remaining_tl", sa.Float(), nullable=False),
            sa.Column("carry_box", sa.Float(), nullable=False),
            sa.Column("carry_tl", sa.Float(), nullable=False),
            sa.Column("daily_need", sa.Float(), nullable=False),
            sa.Column("projected_box", sa.Float(), nullable=False),
            sa.Column("projected_percent", sa.Float(), nullable=False),
            sa.Column("risk_score", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
            sa.ForeignKeyConstraint(["representative_id"], ["representatives.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_table("ims_uploads"):
        op.create_table(
            "ims_uploads",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("file_name", sa.String(length=255), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("month", sa.Integer(), nullable=False),
            sa.Column("quarter", sa.String(length=5), nullable=False),
            sa.Column("sheet_count", sa.Integer(), nullable=False),
            sa.Column("raw_record_count", sa.Integer(), nullable=False),
            sa.Column("fact_record_count", sa.Integer(), nullable=False),
            sa.Column("summary_record_count", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("processing_time", sa.Float(), nullable=False),
            sa.Column("uploaded_by", sa.String(length=120), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("warning_message", sa.Text(), nullable=True),
            sa.Column("uploaded_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_table("ims_raw_data"):
        op.create_table(
            "ims_raw_data",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("upload_id", sa.Integer(), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("month", sa.Integer(), nullable=False),
            sa.Column("quarter", sa.String(length=5), nullable=False),
            sa.Column("sheet_name", sa.String(length=150), nullable=False),
            sa.Column("sheet_type", sa.String(length=50), nullable=False),
            sa.Column("source_row", sa.Integer(), nullable=False),
            sa.Column("representative_id", sa.Integer(), nullable=True),
            sa.Column("product_id", sa.Integer(), nullable=True),
            sa.Column("representative", sa.String(length=150), nullable=True),
            sa.Column("manager", sa.String(length=150), nullable=True),
            sa.Column("product", sa.String(length=150), nullable=True),
            sa.Column("competitor", sa.String(length=150), nullable=True),
            sa.Column("brick", sa.String(length=150), nullable=True),
            sa.Column("market", sa.String(length=150), nullable=True),
            sa.Column("unit", sa.Float(), nullable=False),
            sa.Column("tl", sa.Float(), nullable=False),
            sa.Column("market_share", sa.Float(), nullable=False),
            sa.Column("value_share", sa.Float(), nullable=False),
            sa.Column("growth", sa.Float(), nullable=False),
            sa.Column("raw_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
            sa.ForeignKeyConstraint(["representative_id"], ["representatives.id"]),
            sa.ForeignKeyConstraint(["upload_id"], ["ims_uploads.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if _has_table("ims_raw_data") and not _has_index("ims_raw_data", "ix_ims_raw_period"):
        op.create_index("ix_ims_raw_period", "ims_raw_data", ["year", "month"], unique=False)

    if _has_table("ims_raw_data") and not _has_index("ims_raw_data", "ix_ims_raw_upload"):
        op.create_index("ix_ims_raw_upload", "ims_raw_data", ["upload_id"], unique=False)

    if not _has_table("ims_facts"):
        op.create_table(
            "ims_facts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("upload_id", sa.Integer(), nullable=False),
            sa.Column("raw_data_id", sa.Integer(), nullable=False),
            sa.Column("representative_id", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("month", sa.Integer(), nullable=False),
            sa.Column("quarter", sa.String(length=5), nullable=False),
            sa.Column("report_type", sa.String(length=50), nullable=False),
            sa.Column("unit", sa.Float(), nullable=False),
            sa.Column("tl", sa.Float(), nullable=False),
            sa.Column("market_share", sa.Float(), nullable=False),
            sa.Column("value_share", sa.Float(), nullable=False),
            sa.Column("growth", sa.Float(), nullable=False),
            sa.Column("metrics_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
            sa.ForeignKeyConstraint(["raw_data_id"], ["ims_raw_data.id"]),
            sa.ForeignKeyConstraint(["representative_id"], ["representatives.id"]),
            sa.ForeignKeyConstraint(["upload_id"], ["ims_uploads.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("raw_data_id", name="uq_ims_fact_raw_data"),
        )

    if _has_table("ims_facts") and not _has_index("ims_facts", "ix_ims_fact_period"):
        op.create_index("ix_ims_fact_period", "ims_facts", ["year", "month"], unique=False)

    if _has_table("ims_facts") and not _has_index("ims_facts", "ix_ims_fact_rep_product"):
        op.create_index(
            "ix_ims_fact_rep_product",
            "ims_facts",
            ["representative_id", "product_id"],
            unique=False,
        )

    if not _has_table("ims_summary"):
        op.create_table(
            "ims_summary",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("upload_id", sa.Integer(), nullable=False),
            sa.Column("representative_id", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("month", sa.Integer(), nullable=False),
            sa.Column("quarter", sa.String(length=5), nullable=False),
            sa.Column("unit", sa.Float(), nullable=False),
            sa.Column("tl", sa.Float(), nullable=False),
            sa.Column("market_share", sa.Float(), nullable=False),
            sa.Column("value_share", sa.Float(), nullable=False),
            sa.Column("growth", sa.Float(), nullable=False),
            sa.Column("realization_percent", sa.Float(), nullable=False),
            sa.Column("prime_percent", sa.Float(), nullable=False),
            sa.Column("target_unit", sa.Float(), nullable=False),
            sa.Column("target_tl", sa.Float(), nullable=False),
            sa.Column("bonus_amount", sa.Float(), nullable=False),
            sa.Column("rank", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
            sa.ForeignKeyConstraint(["representative_id"], ["representatives.id"]),
            sa.ForeignKeyConstraint(["upload_id"], ["ims_uploads.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "year", "month", "representative_id", "product_id",
                name="uq_ims_summary_period",
            ),
        )

    if _has_table("ims_summary") and not _has_index("ims_summary", "ix_ims_summary_period"):
        op.create_index(
            "ix_ims_summary_period", "ims_summary", ["year", "month"], unique=False
        )


def downgrade():
    # This is the initial migration. Downgrading to base would require dropping
    # all application tables, which is intentionally out of scope for automated
    # Alembic downgrade (risk of data loss in production).
    # DBA manual action is required if a full schema teardown is needed.
    pass
