"""Force-refresh durable UI read models from an already accepted IMS upload.

This script does not re-import or mutate IMS business facts. It rebuilds only the
published dashboard/region/representative read models so a replacement import
that reused the same upload id cannot keep an older snapshot generation.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import desc, func

from app import create_app
from app.cache.dashboard_cache import DashboardCache
from app.constants.dashboard_constants import DashboardConstants
from app.extensions import db
from app.models import IMSImportJob, IMSUpload, Representative
from app.services.dashboard_service import DashboardService
from app.services.market_analysis_service import MarketAnalysisService
from app.services.persistent_dashboard_snapshot_service import PersistentDashboardSnapshotService
from app.services.persistent_region_snapshot_service import (
    PersistentRegionSnapshotService,
    region_snapshot_sets,
    region_snapshots,
)
from app.services.persistent_representative_snapshot_service import PersistentRepresentativeSnapshotService
from app.services.region_market_service import RegionMarketService
from app.services.region_performance_service import RegionPerformanceService
from config import Config


def _number(value):
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _latest_upload(year: int, month: int):
    return IMSUpload.query.filter_by(
        year=int(year), month=int(month), status="COMPLETED"
    ).order_by(
        desc(IMSUpload.week_number), desc(IMSUpload.completed_at), desc(IMSUpload.id)
    ).first()


def _refresh_dashboard(year: int, month: int):
    service = DashboardService(year=year, month=month)
    cache_key = DashboardConstants.CACHE_KEY_TEMPLATE.format(
        year=year, month=month, rep_id=None
    )
    DashboardCache().invalidate(cache_key)
    payload = service.run()

    national = payload.get("executive_metrics") or {}
    products = national.get("products") or []
    if _number(national.get("target_tl")) <= 0:
        raise RuntimeError("dashboard executive target_tl is empty")
    if _number(national.get("actual_tl")) <= 0:
        raise RuntimeError("dashboard executive actual_tl is empty")
    if _number(national.get("unit_target")) <= 0:
        raise RuntimeError("dashboard executive unit_target is empty")
    if _number(national.get("unit_actual")) <= 0:
        raise RuntimeError("dashboard executive unit_actual is empty")
    if len(products) != 7:
        raise RuntimeError(f"dashboard executive product coverage={len(products)}/7")

    PersistentDashboardSnapshotService.publish(year, month, payload)
    verified = PersistentDashboardSnapshotService.get_active(year, month)
    verified_national = (verified or {}).get("executive_metrics") or {}
    if len(verified_national.get("products") or []) != 7:
        raise RuntimeError("published dashboard snapshot did not retain seven products")

    print(
        "DASHBOARD_READ_MODEL|PASS"
        f"|target_tl={_number(national.get('target_tl')):.2f}"
        f"|actual_tl={_number(national.get('actual_tl')):.2f}"
        f"|target_box={_number(national.get('unit_target')):.2f}"
        f"|actual_box={_number(national.get('unit_actual')):.2f}"
        f"|products={len(products)}"
    )
    return payload


def _prepare_region_payloads(year: int, month: int):
    keys = PersistentRegionSnapshotService.region_keys(year, month)
    prepared = []
    for region_key in keys:
        performance = RegionPerformanceService(region_key, year, month)
        report = performance.report()
        market = RegionMarketService(
            report["region_key"], performance.rep_ids, year, month
        ).build()
        payload = json.dumps(
            PersistentRegionSnapshotService._json_ready(
                {"report": report, "market_analysis": market}
            ),
            ensure_ascii=False,
            separators=(",", ":"),
            default=PersistentRegionSnapshotService._json_default,
        )
        prepared.append((str(report["region_key"]).strip(), payload))
    return prepared


def _refresh_regions(year: int, month: int):
    ims_id, production_id = PersistentRegionSnapshotService.source_identity(year, month)
    if not ims_id:
        raise RuntimeError("region snapshot source upload is missing")

    # Compute every payload while the old ACTIVE generation remains readable.
    # Only after all calculations succeed do we replace the exact generation in
    # one transaction, so requests never see a partially rebuilt region pack.
    prepared = _prepare_region_payloads(year, month)
    if len(prepared) != 11:
        raise RuntimeError(f"region payload coverage={len(prepared)}/11")

    existing = PersistentRegionSnapshotService._existing_set(
        year, month, ims_id, production_id
    )
    try:
        if existing:
            set_id = int(existing.id)
        else:
            result = db.session.execute(region_snapshot_sets.insert().values(
                year=year,
                month=month,
                source_upload_id=ims_id,
                production_upload_id=production_id,
                status=PersistentRegionSnapshotService.STATUS_BUILDING,
                region_count=0,
                created_at=datetime.utcnow(),
            ))
            set_id = int(result.inserted_primary_key[0])

        db.session.execute(
            region_snapshots.delete().where(region_snapshots.c.set_id == set_id)
        )
        for region_key, payload in prepared:
            db.session.execute(region_snapshots.insert().values(
                set_id=set_id,
                region_key=region_key,
                payload_json=payload,
                created_at=datetime.utcnow(),
            ))

        db.session.execute(
            region_snapshot_sets.update().where(
                region_snapshot_sets.c.year == year,
                region_snapshot_sets.c.month == month,
                region_snapshot_sets.c.status == PersistentRegionSnapshotService.STATUS_ACTIVE,
                region_snapshot_sets.c.id != set_id,
            ).values(status=PersistentRegionSnapshotService.STATUS_SUPERSEDED)
        )
        db.session.execute(
            region_snapshot_sets.update().where(
                region_snapshot_sets.c.id == set_id
            ).values(
                status=PersistentRegionSnapshotService.STATUS_ACTIVE,
                region_count=len(prepared),
                activated_at=datetime.utcnow(),
            )
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    verified = PersistentRegionSnapshotService.get_active_all(year, month)
    if len(verified) != 11:
        raise RuntimeError(f"published region snapshot coverage={len(verified)}/11")
    region901 = next(
        (snapshot for key, snapshot in verified.items() if str(key).startswith("901")),
        None,
    )
    if not region901:
        raise RuntimeError("region 901 snapshot is missing")
    totals = (region901.get("market_analysis") or {}).get("totals") or {}
    print(
        "REGION_READ_MODEL|PASS"
        f"|regions={len(verified)}"
        f"|region901_market_box={_number(totals.get('market_unit')):.2f}"
        f"|region901_company_box={_number(totals.get('effective_company_unit', totals.get('company_unit'))):.2f}"
    )
    return verified


def _refresh_representatives(year: int, month: int):
    result = PersistentRepresentativeSnapshotService.build_for_period(
        year, month, force=True
    )
    if result.get("status") not in {"ACTIVE", "REUSED"}:
        raise RuntimeError(f"representative snapshot refresh status={result}")

    murat = Representative.query.filter(
        func.upper(Representative.rep_name) == "MURAT ARSLAN"
    ).first()
    if murat is None:
        raise RuntimeError("Murat Arslan representative row is missing")
    snapshot = PersistentRepresentativeSnapshotService.get_active(
        murat.id, year, month
    )
    if not isinstance(snapshot, dict) or not snapshot:
        raise RuntimeError("Murat Arslan refreshed snapshot is unavailable")
    print(
        "REPRESENTATIVE_READ_MODEL|PASS"
        f"|representatives={result.get('representatives', 0)}|murat_snapshot=1"
    )
    return result


def _verify_market(year: int, month: int, week: int):
    market = MarketAnalysisService(year, month).build()
    groups = market.get("groups") or []
    available = [row for row in groups if row.get("market_available")]
    if not market.get("has_competition"):
        raise RuntimeError(f"market competition still unavailable: {market.get('source_message')}")
    if len(groups) != 7 or len(available) != 7:
        raise RuntimeError(
            f"market product coverage groups={len(groups)}/7 available={len(available)}/7"
        )
    if int(market.get("source_week") or 0) != int(week):
        raise RuntimeError(
            f"market source week={market.get('source_week')} expected={week}"
        )
    if _number(market.get("market_total_value")) <= 0:
        raise RuntimeError("market total is empty")
    if _number(market.get("competitor_total_value")) <= 0:
        raise RuntimeError("competitor total is empty")

    print(
        "MARKET_READ_MODEL|PASS"
        f"|mode={market.get('metric_mode')}"
        f"|source_week={market.get('source_week')}"
        f"|products={len(groups)}|available={len(available)}"
        f"|company_tl={_number(market.get('company_total_tl')):.2f}"
        f"|company_box={_number(market.get('company_total_unit')):.2f}"
        f"|market={_number(market.get('market_total_value')):.2f}"
        f"|competitor={_number(market.get('competitor_total_value')):.2f}"
        f"|share={_number(market.get('company_share_percent')):.2f}"
    )
    return market


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    args = parser.parse_args()

    app = create_app(Config)
    with app.app_context():
        active = IMSImportJob.query.filter(
            IMSImportJob.status.in_((
                IMSImportJob.STATUS_QUEUED,
                IMSImportJob.STATUS_PROCESSING,
            ))
        ).count()
        if active:
            raise SystemExit(f"READ_MODEL_REFRESH_REFUSED|active_imports={active}")

        upload = _latest_upload(args.year, args.month)
        if upload is None:
            raise SystemExit("READ_MODEL_REFRESH_REFUSED|reason=no_completed_upload")
        if int(upload.week_number or 0) != int(args.week):
            raise SystemExit(
                "READ_MODEL_REFRESH_REFUSED|reason=unexpected_latest_week|"
                f"actual={upload.week_number}|expected={args.week}"
            )

        print(
            "READ_MODEL_REFRESH_SOURCE|"
            f"upload={upload.id}|period={args.year:04d}-{args.month:02d}|week={args.week}"
        )
        _refresh_dashboard(args.year, args.month)
        _verify_market(args.year, args.month, args.week)
        _refresh_regions(args.year, args.month)
        _refresh_representatives(args.year, args.month)
        _verify_market(args.year, args.month, args.week)
        print(
            "LIVE_READ_MODEL_REFRESH|PASS|"
            f"upload={upload.id}|period={args.year:04d}-{args.month:02d}|week={args.week}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
