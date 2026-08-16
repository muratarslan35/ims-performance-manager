#!/usr/bin/env python
"""Read-only production audit for January target imports."""
from app import create_app
from app.extensions import db
from app.models import Target, Representative, Product

NAMES = [
    "YAKUP ÇAĞIR", "VEYSİ ÖZDAMAR", "GÖKHAN DUMAN", "MURAT ARSLAN",
    "MUSTAFA ALMAZ", "ÖZGECAN GÜLACAR", "DİYARBAKIR BOŞ", "GÜLBAHAR KARA", "YASİN TİNİ",
]

app = create_app()
with app.app_context():
    rows = (
        db.session.query(Representative.rep_name, Product.product_name, Target.unit_target, Target.tl_target)
        .join(Target, Target.representative_id == Representative.id)
        .join(Product, Product.id == Target.product_id)
        .filter(Target.year == 2026, Target.month == 1, Representative.rep_name.in_(NAMES))
        .order_by(Representative.rep_name, Product.product_name)
        .all()
    )
    print("=== JANUARY_TARGET_AUDIT_BEGIN ===")
    for rep, product, unit, tl in rows:
        print(f"{rep}|{product}|{unit:.6f}|{tl:.6f}")
    print(f"ROW_COUNT|{len(rows)}")
    print("=== JANUARY_TARGET_AUDIT_END ===")
