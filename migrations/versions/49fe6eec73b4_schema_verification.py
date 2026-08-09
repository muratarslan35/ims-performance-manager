"""schema verification

Revision ID: 49fe6eec73b4
Revises: 9f8b1c2d4e6f
Create Date: 2026-08-06 06:04:01.265283

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '49fe6eec73b4'
down_revision = '9f8b1c2d4e6f'
branch_labels = None
depends_on = None


def _has_table(table_name):
    return table_name in set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    # This revision may follow a deployment where the competition branch was
    # already applied. Keep the schema reconciliation safe in that case.
    if not _has_table('target_import_audits'):
        op.create_table('target_import_audits',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('month', sa.Integer(), nullable=False),
    sa.Column('uploaded_by', sa.String(length=150), nullable=True),
    sa.Column('uploaded_at', sa.DateTime(), nullable=False),
    sa.Column('rows_inserted', sa.Integer(), nullable=False),
    sa.Column('rows_updated', sa.Integer(), nullable=False),
    sa.Column('rows_skipped', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.PrimaryKeyConstraint('id')
        )
    if not _has_table('ims_competition_data'):
        op.create_table('ims_competition_data',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('upload_id', sa.Integer(), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('month', sa.Integer(), nullable=False),
    sa.Column('week_number', sa.Integer(), nullable=True),
    sa.Column('sheet_name', sa.String(length=150), nullable=False),
    sa.Column('period_type', sa.String(length=30), nullable=False),
    sa.Column('territory', sa.String(length=150), nullable=False),
    sa.Column('subterritory', sa.String(length=150), nullable=False),
    sa.Column('product_group', sa.String(length=200), nullable=False),
    sa.Column('product_name', sa.String(length=200), nullable=False),
    sa.Column('is_company_product', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_competitor', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('metric_type', sa.String(length=30), nullable=False),
    sa.Column('metric_value', sa.Float(), server_default='0.0', nullable=False),
    sa.Column('is_subtotal', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_grand_total', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('source_row', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['upload_id'], ['ims_uploads.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('upload_id', 'sheet_name', 'period_type', 'year', 'month', 'week_number', 'territory', 'subterritory', 'product_group', 'product_name', 'metric_type', name='uq_competition_grain')
        )
        with op.batch_alter_table('ims_competition_data', schema=None) as batch_op:
            batch_op.create_index('ix_competition_period', ['year', 'month', 'week_number'], unique=False)
            batch_op.create_index('ix_competition_sheet', ['sheet_name'], unique=False)
            batch_op.create_index('ix_competition_territory', ['territory', 'subterritory'], unique=False)
            batch_op.create_index(batch_op.f('ix_ims_competition_data_upload_id'), ['upload_id'], unique=False)

    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.alter_column('action',
               existing_type=sa.VARCHAR(length=255),
               nullable=False)

    with op.batch_alter_table('import_audit_logs', schema=None) as batch_op:
        batch_op.alter_column('status',
               existing_type=sa.VARCHAR(length=30),
               type_=sa.String(length=50),
               existing_nullable=False)


    with op.batch_alter_table('ims_uploads', schema=None) as batch_op:
        batch_op.alter_column('quarter',
               existing_type=sa.VARCHAR(length=5),
               nullable=True)
        batch_op.alter_column('status',
               existing_type=sa.VARCHAR(length=30),
               type_=sa.String(length=50),
               existing_nullable=False)
        batch_op.alter_column('uploaded_by',
               existing_type=sa.VARCHAR(length=120),
               type_=sa.String(length=150),
               existing_nullable=True)

    with op.batch_alter_table('manual_match_queue', schema=None) as batch_op:
        batch_op.alter_column('entity_type',
               existing_type=sa.VARCHAR(length=30),
               type_=sa.String(length=50),
               existing_nullable=False)
        batch_op.alter_column('source_value',
               existing_type=sa.VARCHAR(length=200),
               type_=sa.String(length=255),
               existing_nullable=True)
        batch_op.alter_column('normalized_value',
               existing_type=sa.VARCHAR(length=200),
               type_=sa.String(length=255),
               existing_nullable=True)
        batch_op.alter_column('worksheet',
               existing_type=sa.VARCHAR(length=150),
               type_=sa.String(length=100),
               existing_nullable=True)
        batch_op.drop_constraint(batch_op.f('uq_match_queue_entity_name'), type_='unique')
        batch_op.create_unique_constraint('uq_manual_match_entity', ['entity_type', 'ims_name'])



    with op.batch_alter_table('representatives', schema=None) as batch_op:
        batch_op.alter_column('territory',
               existing_type=sa.VARCHAR(length=100),
               type_=sa.String(length=150),
               existing_nullable=True)
        batch_op.alter_column('manager',
               existing_type=sa.VARCHAR(length=120),
               type_=sa.String(length=150),
               existing_nullable=True)
        batch_op.alter_column('team',
               existing_type=sa.VARCHAR(length=100),
               type_=sa.String(length=150),
               existing_nullable=True)

    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.alter_column('setting_key',
               existing_type=sa.VARCHAR(length=120),
               type_=sa.String(length=150),
               existing_nullable=False)
        batch_op.alter_column('setting_value',
               existing_type=sa.VARCHAR(length=255),
               nullable=True)


    # ### end Alembic commands ###


def downgrade():
    pass
