"""Refresh July quota realization read models without touching IMS/production facts."""
from __future__ import annotations

import argparse
import time

from sqlalchemy import func

from app import create_app
from app.extensions import db
from app.models import (IMSImportJob, IMSSummary, IMSUpload, Product, Target,
                        ProductionResult, ProductionNationalProductResult)
from app.services.period_service import PeriodService
from app.services.production_result_service import ProductionResultService
from app.services.persistent_dashboard_snapshot_service import PersistentDashboardSnapshotService
from app.services.persistent_region_snapshot_service import PersistentRegionSnapshotService
from app.services.ims_publication_service import IMSPublicationService
from app.services.persistent_representative_snapshot_service import PersistentRepresentativeSnapshotService
from config import Config
from scripts.refresh_live_read_models import (
    _refresh_dashboard, _refresh_regions, _refresh_representatives,
)


def _wait_for_idle(deadline):
    while True:
        active = IMSImportJob.query.filter(IMSImportJob.status.in_((
            IMSImportJob.STATUS_QUEUED, IMSImportJob.STATUS_PROCESSING,
        ))).count()
        db.session.rollback()
        if not active:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Quota refresh queued behind {active} IMS jobs; deadline reached")
        print(f"QUOTA_REFRESH_WAIT|ims_jobs={active}", flush=True)
        time.sleep(20)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--month", type=int, default=7)
    args = parser.parse_args()
    app = create_app(Config)
    with app.app_context():
        deadline = time.monotonic() + 3600
        _wait_for_idle(deadline)
        quota = ProductionResultService.quota_product_months([(args.year, args.month)])
        product = Product.query.filter(func.upper(Product.product_name) == "FENTIVAG").first()
        if product is not None:
            upload = ProductionResultService.final_upload(args.year, args.month)
            production_rows = (ProductionResult.query.filter_by(
                upload_id=upload.id, product_id=product.id).all() if upload else [])
            national_row = (ProductionNationalProductResult.query.filter_by(
                upload_id=upload.id, product_id=product.id).first() if upload else None)
            ims_rows = IMSSummary.query.filter_by(
                year=args.year, month=args.month, product_id=product.id).all()
            print("QUOTA_PREFLIGHT|upload=%s|production_rows=%s|production_positive=%s|"
                  "national_present=%s|national_tl=%s|national_unit=%s|"
                  "ims_rows=%s|ims_positive=%s|approved=%s" % (
                      upload.id if upload else None, len(production_rows),
                      sum(1 for row in production_rows if (row.actual_tl or 0) > 0 or (row.actual_unit or 0) > 0),
                      national_row is not None,
                      national_row.actual_tl if national_row else None,
                      national_row.actual_unit if national_row else None,
                      len(ims_rows),
                      sum(1 for row in ims_rows if (row.tl or 0) > 0 or (row.unit or 0) > 0),
                      (args.year, args.month) in quota.get(product.id, []),
                  ), flush=True)
        if product is None or (args.year, args.month) not in quota.get(product.id, []):
            raise RuntimeError("Final production + nationwide IMS do not approve Fentivag quota exit")
        allocated = db.session.query(func.sum(Target.tl_target)).filter_by(
            year=args.year, month=args.month, product_id=product.id,
        ).scalar() or 0
        if allocated <= 0:
            raise RuntimeError("July Fentivag allocated TL quota is unavailable")
        active = PeriodService.get_active_period()
        end_month = min(9, int(active["month"])) if int(active["year"]) == args.year else 9
        for month in range(args.month, end_month + 1):
            if not IMSUpload.query.filter_by(year=args.year, month=month, status="COMPLETED").first():
                continue
            _wait_for_idle(deadline)
            print(f"QUOTA_REFRESH_START|{args.year}-{month:02d}", flush=True)
            _refresh_dashboard(args.year, month)
            try:
                _refresh_regions(args.year, month)
            except RuntimeError:
                ims_id, production_id = PersistentRegionSnapshotService.source_identity(args.year, month)
                pending = IMSPublicationService.pending_job(args.year, month)
                existing = PersistentRegionSnapshotService._existing_set(
                    args.year, month, ims_id, production_id)
                raw_count = (len(PersistentRegionSnapshotService._payloads_from_set(existing.id))
                             if existing else 0)
                print(f"REGION_VISIBILITY_DIAGNOSTIC|ims={ims_id}|production={production_id}"
                      f"|pending_job={pending.id if pending else None}"
                      f"|pending_status={pending.status if pending else None}"
                      f"|set_id={existing.id if existing else None}"
                      f"|set_status={existing.status if existing else None}"
                      f"|raw_regions={raw_count}", flush=True)
                raise
            _refresh_representatives(args.year, month)
            if month == args.month:
                dashboard = PersistentDashboardSnapshotService.get_active(args.year, month)
                products = (dashboard or {}).get("executive_metrics", {}).get("products", [])
                row = next((item for item in products if item.get("product_id") == product.id), None)
                if not row or round(float(row.get("actual_tl") or 0), 2) != round(float(row.get("target_tl") or 0), 2):
                    raise RuntimeError("Published national July Fentivag TL quota did not close")
                regions = PersistentRegionSnapshotService.get_active_all(args.year, month)
                if not regions:
                    raise RuntimeError("Published July region snapshots unavailable")
                for key, payload in regions.items():
                    monthly = ((payload or {}).get("report") or {}).get("periods", {}).get("monthly", {})
                    item = next((row for row in monthly.get("products", []) if row.get("product_id") == product.id), None)
                    if item and float(item.get("target_tl") or 0) > 0:
                        if round(float(item.get("actual_tl") or 0), 2) != round(float(item["target_tl"]), 2):
                            raise RuntimeError(f"July region {key} Fentivag quota did not close")
                ids = PersistentRepresentativeSnapshotService.representative_ids(args.year, month)
                for representative_id in ids:
                    target = Target.query.filter_by(year=args.year, month=month,
                        representative_id=representative_id, product_id=product.id).first()
                    if target is None or not target.tl_target:
                        continue
                    snapshot = PersistentRepresentativeSnapshotService.get_active(
                        representative_id, args.year, month)
                    if not snapshot:
                        raise RuntimeError(f"Representative {representative_id} snapshot missing")
                    monthly = (snapshot.get("snapshots") or {}).get("monthly") or {}
                    item = next((row for row in monthly.get("products", [])
                                 if (row.get("product_id") or (row.get("product") or {}).get("id")) == product.id), None)
                    if not item or round(float(item.get("actual_tl") or 0), 2) != round(float(target.tl_target), 2):
                        raise RuntimeError(f"Representative {representative_id} July Fentivag quota did not close")
                print(f"JULY_QUOTA_ACCEPTANCE|PASS|target_tl={allocated:.2f}|regions={len(regions)}|representatives={len(ids)}", flush=True)
            print(f"QUOTA_REFRESH_DONE|{args.year}-{month:02d}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
