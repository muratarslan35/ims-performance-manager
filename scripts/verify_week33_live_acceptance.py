"""Read-only acceptance checks for the published Week 33 IMS snapshot."""
from __future__ import annotations

import json
import math

import sqlalchemy as sa

from app import create_app
from app.extensions import db
from app.models import IMSImportJob, IMSUpload, Representative
from app.services.persistent_dashboard_snapshot_service import PersistentDashboardSnapshotService
from app.services.persistent_region_snapshot_service import PersistentRegionSnapshotService
from app.services.persistent_representative_snapshot_service import (
    PersistentRepresentativeSnapshotService,
    representative_snapshots,
)
from app.services.period_service import PeriodService
from config import Config


def close(left, right):
    return math.isclose(float(left or 0), float(right or 0), rel_tol=1e-7, abs_tol=0.01)


def main() -> int:
    app = create_app(Config)
    with app.app_context():
        upload = IMSUpload.query.filter_by(
            year=2026, month=8, week_number=33, status="COMPLETED"
        ).order_by(IMSUpload.id.desc()).first()
        assert upload and upload.id == 46, getattr(upload, "id", None)
        period = PeriodService.get_active_period()
        assert int(period.get("upload_id") or 0) == 46, period
        assert int(period.get("week_number") or 0) == 33, period

        job = IMSImportJob.query.filter_by(ims_upload_id=46).order_by(IMSImportJob.id.desc()).first()
        assert job and job.status == IMSImportJob.STATUS_COMPLETED
        summary = json.loads(job.result_summary or "{}")
        assert summary.get("publication_ready") is True, summary

        assert PersistentDashboardSnapshotService.source_identity(2026, 8)[0] == 46
        regions = PersistentRegionSnapshotService.get_active_all(2026, 8)
        assert len(regions) == 11, len(regions)
        travazol_regions = 0
        for key, snapshot in regions.items():
            market = snapshot.get("market_analysis") or {}
            assert int(market.get("upload_id") or 0) == 46, (key, market.get("upload_id"))
            travazol = next(
                row for row in (market.get("rows") or [])
                if str(row.get("product_name") or "").upper() == "TRAVAZOL"
            )
            rivals = travazol.get("rivals") or []
            assert rivals, (key, "missing Travazol rivals")
            assert all(str(r.get("name") or "").strip() for r in rivals), key
            travazol_regions += 1

        assert PersistentRepresentativeSnapshotService.source_identity(2026, 8)[0] == 46
        set_id = PersistentRepresentativeSnapshotService._visible_set_id(2026, 8)
        payloads = db.session.execute(
            sa.select(representative_snapshots.c.payload_json).where(
                representative_snapshots.c.set_id == set_id
            )
        ).scalars().all()
        assert len(payloads) == 113, len(payloads)
        for raw in payloads:
            market = (((json.loads(raw).get("snapshots") or {}).get("monthly") or {}).get("market_analysis") or {})
            assert int(market.get("upload_id") or 0) == 46
            totals = market.get("totals") or {}
            assert close(totals.get("actual_unit") + totals.get("competitor_unit"), totals.get("market_unit"))

        murat = Representative.query.filter(
            db.func.upper(Representative.rep_name) == "MURAT ARSLAN"
        ).first()
        assert murat
        snapshot = PersistentRepresentativeSnapshotService.get_active(murat.id, 2026, 8)
        market = (((snapshot.get("snapshots") or {}).get("monthly") or {}).get("market_analysis") or {})
        assert int(market.get("upload_id") or 0) == 46
        totals = market.get("totals") or {}
        assert close(totals.get("actual_unit") + totals.get("competitor_unit"), totals.get("market_unit"))
        print(
            "WEEK33_LIVE_ACCEPTANCE|PASS|upload=46|week=33|regions=11|"
            f"travazol_regions={travazol_regions}|representatives=113|"
            f"murat_company={float(totals.get('actual_unit') or 0):.2f}|"
            f"murat_competitor={float(totals.get('competitor_unit') or 0):.2f}|"
            f"murat_market={float(totals.get('market_unit') or 0):.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
