"""Repair only stale July Fentivag representative snapshot members."""
from __future__ import annotations

from sqlalchemy import func

from app import create_app
from app.models import Product, Target
from app.services.production_result_service import ProductionResultService
from app.services.persistent_representative_snapshot_service import PersistentRepresentativeSnapshotService
from config import Config


def _product_row(rows, product_id):
    return next(
        (
            row for row in rows or []
            if int(row.get("product_id") or (row.get("product") or {}).get("id") or 0)
            == int(product_id)
        ),
        None,
    )


def _closed(row, target):
    return (
        row is not None
        and float(target or 0) > 0
        and round(float(row.get("actual_tl") or 0), 2) == round(float(target or 0), 2)
    )


def main():
    year, month = 2026, 7
    app = create_app(Config)
    with app.app_context():
        product = Product.query.filter(func.upper(Product.product_name) == "FENTIVAG").first()
        if product is None:
            raise RuntimeError("Fentivag product missing")
        product_id = int(product.id)
        quota = ProductionResultService.quota_product_months([(year, month)])
        if (year, month) not in quota.get(product_id, []):
            raise RuntimeError("July Fentivag quota exit is not approved")

        ims_id, production_id = PersistentRepresentativeSnapshotService.source_identity(year, month)
        ids = PersistentRepresentativeSnapshotService.representative_ids(year, month, ims_id)
        exact = PersistentRepresentativeSnapshotService._latest_exact_active(
            year, month, ims_id, production_id
        )
        if exact is None:
            raise RuntimeError("Exact July representative generation unavailable")

        snapshots = PersistentRepresentativeSnapshotService._payloads_from_set(exact.id, ids)
        if len(snapshots) != len(ids):
            raise RuntimeError(f"Published representative coverage {len(snapshots)}/{len(ids)}")

        targets = {
            int(row.representative_id): float(row.tl_target or 0)
            for row in Target.query.filter(
                Target.year == year,
                Target.month == month,
                Target.product_id == product_id,
                Target.representative_id.in_(ids),
            ).all()
            if row.tl_target
        }
        stale = []
        for representative_id, target in targets.items():
            monthly = ((snapshots.get(representative_id) or {}).get("snapshots") or {}).get("monthly") or {}
            if not _closed(_product_row(monthly.get("products"), product_id), target):
                stale.append(int(representative_id))

        if stale:
            print(
                "JULY_REPRESENTATIVE_QUOTA_STALE|ids=" + ",".join(str(item) for item in stale),
                flush=True,
            )
            result = PersistentRepresentativeSnapshotService.rebuild_exact_members(
                year, month, stale, set_id=int(exact.id)
            )
            if result.get("status") not in {"ACTIVE", "REUSED"}:
                raise RuntimeError(f"Selective July representative repair failed: {result}")

        exact = PersistentRepresentativeSnapshotService._latest_exact_active(
            year, month, ims_id, production_id
        )
        snapshots = (
            PersistentRepresentativeSnapshotService._payloads_from_set(exact.id, ids)
            if exact else {}
        )
        for representative_id, target in targets.items():
            monthly = ((snapshots.get(representative_id) or {}).get("snapshots") or {}).get("monthly") or {}
            if not _closed(_product_row(monthly.get("products"), product_id), target):
                raise RuntimeError(
                    f"Representative {representative_id} July Fentivag quota still open"
                )

        print(
            "JULY_REPRESENTATIVE_QUOTA_REPAIR|PASS|"
            f"rebuilt={len(stale)}|representatives={len(ids)}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
