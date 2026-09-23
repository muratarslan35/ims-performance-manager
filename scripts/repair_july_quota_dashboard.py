"""Repair only the published July national dashboard quota read model."""
from __future__ import annotations

from sqlalchemy import func

from app import create_app
from app.cache.dashboard_cache import DashboardCache
from app.constants.dashboard_constants import DashboardConstants
from app.extensions import db
from app.models import IMSImportJob, Product
from app.services.dashboard_service import DashboardService
from app.services.production_result_service import ProductionResultService
from app.services.persistent_dashboard_snapshot_service import PersistentDashboardSnapshotService
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


def _closed(row):
    if row is None:
        return False
    target = float(row.get("target_tl") or 0)
    return target > 0 and round(float(row.get("actual_tl") or 0), 2) == round(target, 2)


def main():
    year, month = 2026, 7
    app = create_app(Config)
    with app.app_context():
        active = IMSImportJob.query.filter(
            IMSImportJob.status.in_((IMSImportJob.STATUS_QUEUED, IMSImportJob.STATUS_PROCESSING))
        ).count()
        if active:
            raise RuntimeError(f"July dashboard repair refused while {active} IMS jobs are active")

        product = Product.query.filter(func.upper(Product.product_name) == "FENTIVAG").first()
        if product is None:
            raise RuntimeError("Fentivag product missing")
        product_id = int(product.id)
        quota = ProductionResultService.quota_product_months([(year, month)])
        if (year, month) not in quota.get(product_id, []):
            raise RuntimeError("July Fentivag quota exit is not approved")

        ims_id, production_id = PersistentDashboardSnapshotService.source_identity(year, month)
        cache_key = DashboardConstants.CACHE_KEY_TEMPLATE.format(
            year=year, month=month, rep_id=None
        )
        DashboardCache().invalidate(cache_key)
        payload = DashboardService(year=year, month=month).run()
        row = _product_row(
            (payload.get("executive_metrics") or {}).get("products"), product_id
        )
        if not _closed(row):
            raise RuntimeError("Fresh July national dashboard still does not close Fentivag quota")

        PersistentDashboardSnapshotService.publish(year, month, payload)
        verified = PersistentDashboardSnapshotService.get_generation_for_source(
            year, month, ims_id, production_id
        ) or {}
        verified_row = _product_row(
            (verified.get("executive_metrics") or {}).get("products"), product_id
        )
        if not _closed(verified_row):
            raise RuntimeError("Published exact-source July dashboard did not retain Fentivag quota")

        print(
            "JULY_DASHBOARD_QUOTA_REPAIR|PASS|"
            f"ims={ims_id}|production={production_id}|"
            f"target_tl={float(verified_row.get('target_tl') or 0):.2f}",
            flush=True,
        )
        db.session.rollback()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
