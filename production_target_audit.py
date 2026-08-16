#!/usr/bin/env python
"""Read-only production diagnostics for January target imports."""
from app import create_app
from app.extensions import db
from app.models import Target, Representative, RepresentativeAlias, Product
from app.services.alias_service import AliasService

NAMES = [
    "YAKUP ÇAĞIR", "VEYSİ ÖZDAMAR", "GÖKHAN DUMAN", "MURAT ARSLAN",
    "MUSTAFA ALMAZ", "ÖZGECAN GÜLACAR", "DİYARBAKIR BOŞ", "GÜLBAHAR KARA", "YASİN TİNİ",
]

app = create_app()
with app.app_context():
    print("=== JANUARY_TARGET_DIAGNOSTIC_BEGIN ===")
    print(f"JAN_TOTAL_TARGET_ROWS|{Target.query.filter_by(year=2026, month=1).count()}")
    print(f"JAN_DISTINCT_REPS|{db.session.query(Target.representative_id).filter_by(year=2026, month=1).distinct().count()}")

    for requested in NAMES:
        norm = AliasService.normalize(requested)
        reps = Representative.query.all()
        exact_norm = [r for r in reps if AliasService.normalize(r.rep_name) == norm]
        alias_rows = RepresentativeAlias.query.all()
        aliases = [a for a in alias_rows if AliasService.normalize(a.alias_name) == norm]
        resolved_ids = {r.id for r in exact_norm} | {a.representative_id for a in aliases}
        fuzzy = [r for r in reps if norm in AliasService.normalize(r.rep_name) or AliasService.normalize(r.rep_name) in norm]

        print(f"REQUESTED|{requested}|NORM|{norm}")
        print("MASTER_MATCHES|" + ";".join(f"{r.id}:{r.rep_name}:{r.active}" for r in exact_norm))
        print("ALIAS_MATCHES|" + ";".join(f"{a.representative_id}:{a.alias_name}" for a in aliases))
        print("FUZZY_MASTER|" + ";".join(f"{r.id}:{r.rep_name}:{r.active}" for r in fuzzy[:10]))

        for rid in sorted(resolved_ids):
            rep = db.session.get(Representative, rid)
            rows = (
                db.session.query(Product.product_name, Target.unit_target, Target.tl_target)
                .join(Target, Target.product_id == Product.id)
                .filter(Target.year == 2026, Target.month == 1, Target.representative_id == rid)
                .order_by(Product.product_name).all()
            )
            print(f"REP_TARGET_COUNT|{rid}|{rep.rep_name if rep else '?'}|{len(rows)}")
            for product, unit, tl in rows:
                print(f"TARGET|{rid}|{rep.rep_name}|{product}|{unit:.6f}|{tl:.6f}")

    print("=== ALL_JAN_TARGET_REPS ===")
    all_rep_counts = (
        db.session.query(Representative.id, Representative.rep_name, db.func.count(Target.id))
        .join(Target, Target.representative_id == Representative.id)
        .filter(Target.year == 2026, Target.month == 1)
        .group_by(Representative.id, Representative.rep_name)
        .order_by(Representative.rep_name).all()
    )
    for rid, name, count in all_rep_counts:
        print(f"JAN_REP|{rid}|{name}|{count}")
    print("=== JANUARY_TARGET_DIAGNOSTIC_END ===")
