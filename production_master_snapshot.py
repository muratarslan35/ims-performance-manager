#!/usr/bin/env python
"""Create a read-only master/data integrity fingerprint for production deploy logs."""
import hashlib
import json
from decimal import Decimal
from app import create_app
from app.extensions import db
from app.models import Product, Representative, Setting, PrimeRule, Target


def digest(rows):
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

app = create_app()
with app.app_context():
    reps = [[r.id,r.rep_code,r.ims_code,r.sap_code,r.rep_name,r.region,r.city,r.district,r.territory,r.manager,r.team,r.active] for r in Representative.query.order_by(Representative.id)]
    products = [[p.id,p.product_code,p.product_name,p.ims_name,str(p.unit_price),p.display_order,p.is_active,p.is_prime_product,str(p.required_percent),p.include_total_tl] for p in Product.query.order_by(Product.id)]
    settings = [[s.id,s.setting_key,s.setting_value,s.category,s.description] for s in Setting.query.order_by(Setting.id)]
    rules = [[r.id,r.product_id,r.required_percent,r.include_in_prime,r.include_in_total_tl,r.active,str(r.valid_from),str(r.valid_to)] for r in PrimeRule.query.order_by(PrimeRule.id)]
    jan_targets = Target.query.filter_by(year=2026, month=1).all()
    jan_tl = sum((Decimal(str(t.tl_target or 0)) for t in jan_targets), Decimal("0"))
    jan_units = sum((Decimal(str(t.unit_target or 0)) for t in jan_targets), Decimal("0"))
    print("=== MASTER_INTEGRITY_SNAPSHOT ===")
    print(f"REPRESENTATIVES|{len(reps)}|{digest(reps)}")
    print(f"PRODUCTS|{len(products)}|{digest(products)}")
    print(f"SETTINGS|{len(settings)}|{digest(settings)}")
    print(f"PRIME_RULES|{len(rules)}|{digest(rules)}")
    print(f"JAN_TARGET_ROWS|{len(jan_targets)}")
    print(f"JAN_TARGET_TL|{jan_tl}")
    print(f"JAN_TARGET_UNITS|{jan_units}")
    print("=== MASTER_INTEGRITY_SNAPSHOT_END ===")
