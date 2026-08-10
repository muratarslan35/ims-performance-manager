"""Update products with the current July IMS unit prices.

Revision ID: i4d5e6f7a8b9
Revises: h3c4d5e6f7a8
Create Date: 2026-08-10
"""

from alembic import op


revision = "i4d5e6f7a8b9"
down_revision = "h3c4d5e6f7a8"
branch_labels = None
depends_on = None


CURRENT_PRICES = {
    "ACNEMIX": 230.57,
    "BRIMODER": 827.56,
    "FENTIVAG": 179.10,
    "MIXOVUL": 160.89,
    "MONUROL": 100.37,
    "STIDERM": 100.37,
    "TRAVAZOL": 128.31,
}

PREVIOUS_PRICES = {
    "ACNEMIX": 200.63,
    "BRIMODER": 720.08,
    "FENTIVAG": 155.84,
    "MIXOVUL": 140.00,
    "MONUROL": 87.34,
    "STIDERM": 87.34,
    "TRAVAZOL": 111.65,
}


def _apply(prices):
    for product_code, unit_price in prices.items():
        op.execute(
            "UPDATE products SET unit_price = {price} "
            "WHERE product_code = '{code}'".format(price=unit_price, code=product_code)
        )


def upgrade():
    _apply(CURRENT_PRICES)


def downgrade():
    _apply(PREVIOUS_PRICES)
