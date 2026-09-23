"""Fast read-only acceptance for published July Fentivag quota snapshots."""
from __future__ import annotations

from sqlalchemy import func

from app import create_app
from app.extensions import db
from app.models import Product, Target
from app.services.production_result_service import ProductionResultService
from app.services.persistent_dashboard_snapshot_service import PersistentDashboardSnapshotService
from app.services.persistent_region_snapshot_service import PersistentRegionSnapshotService
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


def _closed(row, target=None):
    if row is None:
        return False
    expected = float(target if target is not None else row.get("target_tl") or 0)
    return expected > 0 and round(float(row.get("actual_tl") or 0), 2) == round(expected, 2)


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

        dashboard = PersistentDashboardSnapshotService.get_active(year, month) or {}
        dashboard_row = _product_row(
            (dashboard.get("executive_metrics") or {}).get("products"), product_id
        )
        if not _closed(dashboard_row):
            raise RuntimeError("Published national July Fentivag quota did not close")

        regions = PersistentRegionSnapshotService.get_active_all(year, month)
        if len(regions) != 11:
            raise RuntimeError(f"Published July regions {len(regions)}/11")
        for region_key, payload in regions.items():
            monthly = (((payload or {}).get("report") or {}).get("periods") or {}).get("monthly") or {}
            row = _product_row(monthly.get("products"), product_id)
            if row and float(row.get("target_tl") or 0) > 0 and not _closed(row):
                raise RuntimeError(f"July region {region_key} Fentivag quota did not close")

        ims_id, production_id = PersistentRepresentativeSnapshotService.source_identity(year, month)
        ids = PersistentRepresentativeSnapshotService.representative_ids(year, month, ims_id)
        exact = PersistentRepresentativeSnapshotService._latest_exact_active(
            year, month, ims_id, production_id
        )
        snapshots = (
            PersistentRepresentativeSnapshotService._payloads_from_set(exact.id, ids)
            if exact else {}
        )
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
        for representative_id, target in targets.items():
            monthly = ((snapshots.get(representative_id) or {}).get("snapshots") or {}).get("monthly") or {}
            if not _closed(_product_row(monthly.get("products"), product_id), target):
                raise RuntimeError(
                    f"Representative {representative_id} July Fentivag quota did not close"
                )
        allocated = sum(targets.values())
        print(
            "JULY_QUOTA_FAST_ACCEPTANCE|PASS|"
            f"target_tl={allocated:.2f}|regions={len(regions)}|representatives={len(ids)}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
