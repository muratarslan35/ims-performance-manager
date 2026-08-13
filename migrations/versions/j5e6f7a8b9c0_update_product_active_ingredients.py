"""Populate verified active ingredients for managed products.

Revision ID: j5e6f7a8b9c0
Revises: i4d5e6f7a8b9
Create Date: 2026-08-13
"""

from alembic import op


revision = "j5e6f7a8b9c0"
down_revision = "i4d5e6f7a8b9"
branch_labels = None
depends_on = None


ACTIVE_INGREDIENTS = {
    "ACNEMIX": "Benzoil peroksit + Eritromisin",
    "BRIMODER": "Brimonidin tartarat",
    "FENTIVAG": "Fentikonazol nitrat",
    "MIXOVUL": "Metronidazol + Mikonazol nitrat + Lidokain",
    "MONUROL": "Fosfomisin trometamol",
    "STIDERM": "Mepiramin maleat + Lidokain hidroklorür + Dekspantenol",
    "TRAVAZOL": "İzokonazol nitrat + Diflukortolon valerat",
}


def upgrade():
    for product_code, molecule in ACTIVE_INGREDIENTS.items():
        escaped = molecule.replace("'", "''")
        op.execute(
            "UPDATE products SET molecule = '{molecule}' "
            "WHERE UPPER(product_code) = '{code}' OR UPPER(product_name) = '{code}'".format(
                molecule=escaped,
                code=product_code,
            )
        )


def downgrade():
    for product_code in ACTIVE_INGREDIENTS:
        op.execute(
            "UPDATE products SET molecule = NULL "
            "WHERE UPPER(product_code) = '{code}' OR UPPER(product_name) = '{code}'".format(
                code=product_code,
            )
        )
