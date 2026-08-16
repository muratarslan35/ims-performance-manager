"""Ensure Fentivag exists and is active in the managed product master.

Revision ID: n9c0d1e2f3a4
Revises: m8b9c0d1e2f3
Create Date: 2026-08-16
"""

from alembic import op


revision = "n9c0d1e2f3a4"
down_revision = "m8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        INSERT INTO products (
            product_code,
            product_name,
            ims_name,
            molecule,
            unit_price,
            display_order,
            is_active,
            is_prime_product,
            required_percent,
            include_total_tl,
            created_at
        )
        SELECT
            'FENTIVAG',
            'Fentivag',
            'Fentivag',
            'Fentikonazol nitrat',
            179.10,
            7,
            1,
            0,
            0,
            1,
            CURRENT_TIMESTAMP
        WHERE NOT EXISTS (
            SELECT 1 FROM products WHERE UPPER(product_code) = 'FENTIVAG'
        )
        """
    )
    op.execute(
        """
        UPDATE products
        SET is_active = 1,
            product_code = 'FENTIVAG',
            product_name = 'Fentivag',
            ims_name = COALESCE(NULLIF(ims_name, ''), 'Fentivag'),
            molecule = COALESCE(NULLIF(molecule, ''), 'Fentikonazol nitrat'),
            unit_price = CASE WHEN unit_price IS NULL OR unit_price <= 0 THEN 179.10 ELSE unit_price END,
            display_order = CASE WHEN display_order IS NULL OR display_order <= 0 THEN 7 ELSE display_order END,
            include_total_tl = 1
        WHERE UPPER(product_code) = 'FENTIVAG'
           OR UPPER(product_name) = 'FENTIVAG'
        """
    )


def downgrade():
    op.execute(
        "UPDATE products SET is_active = 0 WHERE UPPER(product_code) = 'FENTIVAG'"
    )
