"""Reset IMS transactional data for a clean January reload.

Revision ID: k6f7a8b9c0d1
Revises: j5e6f7a8b9c0
Create Date: 2026-08-14
"""

from alembic import op
import sqlalchemy as sa


revision = "k6f7a8b9c0d1"
down_revision = "j5e6f7a8b9c0"
branch_labels = None
depends_on = None


# Child tables must be cleared before ims_uploads because production enables
# foreign-key enforcement. Master/configuration tables are intentionally absent.
IMS_TRANSACTION_TABLES = (
    "recovery_summary",
    "ims_competition_data",
    "import_audit_logs",
    "manual_match_queue",
    "ims_facts",
    "ims_summary",
    "ims_raw_data",
    "representative_brick_assignments",
    "ims_uploads",
    "target_import_audits",
    "targets",
)

def upgrade():
    connection = op.get_bind()
    existing = set(sa.inspect(connection).get_table_names())
    for table_name in IMS_TRANSACTION_TABLES:
        if table_name in existing:
            connection.execute(sa.text(f'DELETE FROM "{table_name}"'))

    remaining_rows = {
        table_name: connection.execute(
            sa.text(f'SELECT COUNT(*) FROM "{table_name}"')
        ).scalar_one()
        for table_name in IMS_TRANSACTION_TABLES
        if table_name in existing
    }
    uncleared = {name: count for name, count in remaining_rows.items() if count}
    if uncleared:
        raise RuntimeError(f"IMS transactional reset failed: {uncleared}")

    # A clean SQLite deployment should restart generated identifiers as well.
    if connection.dialect.name == "sqlite" and "sqlite_sequence" in existing:
        connection.execute(
            sa.text("DELETE FROM sqlite_sequence WHERE name IN :names").bindparams(
                sa.bindparam("names", expanding=True)
            ),
            {"names": list(IMS_TRANSACTION_TABLES)},
        )


def downgrade():
    # Production creates a timestamped database backup before migrations.
    # Deleted business rows cannot be reconstructed safely from schema alone.
    pass
