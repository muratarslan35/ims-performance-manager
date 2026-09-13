import json

import sqlalchemy as sa

from app import create_app
from app.extensions import db
from app.services.persistent_region_snapshot_service import PersistentRegionSnapshotService
from app.services.persistent_representative_snapshot_service import (
    PersistentRepresentativeSnapshotService,
    representative_snapshot_sets,
    representative_snapshots,
)
from config import Config


class DiagnosticConfig(Config):
    TESTING = True


app = create_app(DiagnosticConfig)
with app.app_context():
    ims_id, production_id = PersistentRegionSnapshotService.source_identity(2026, 8)
    current = PersistentRegionSnapshotService._existing_set(2026, 8, ims_id, production_id)
    print(f"REGION_SOURCE|ims_id={ims_id}|production_id={production_id}")
    print(
        f"REGION_SET|id={getattr(current, 'id', None)}"
        f"|status={getattr(current, 'status', None)}"
        f"|count={getattr(current, 'region_count', None)}"
    )
    payloads = PersistentRegionSnapshotService._payloads_from_set(current.id) if current else {}
    print(f"REGION_PAYLOAD_COUNT|{len(payloads)}")
    for region_key, snapshot in payloads.items():
        market = snapshot.get("market_analysis") or {}
        rows = market.get("rows") or []
        totals = market.get("totals") or {}
        travazol = next(
            (row for row in rows if str(row.get("product_name") or "").upper() == "TRAVAZOL"),
            {},
        )
        rivals = travazol.get("rivals") or []
        positive = [
            rival for rival in rivals
            if str(rival.get("name") or "").strip() and float(rival.get("unit") or 0) > 0
        ]
        row_math = all(
            abs(
                float(row.get("company_unit") or 0)
                + float(row.get("competitor_unit") or 0)
                - float(row.get("market_unit") or 0)
            ) <= 0.01
            for row in rows
        )
        total_math = abs(
            float(totals.get("company_unit") or 0)
            + float(totals.get("competitor_unit") or 0)
            - float(totals.get("market_unit") or 0)
        ) <= 0.01
        print(
            "REGION_DIAG"
            f"|key={region_key}|rows={len(rows)}"
            f"|upload={market.get('upload_id')}"
            f"|source={market.get('market_share_source')}"
            f"|travazol_competitor={travazol.get('competitor_unit')}"
            f"|rivals={len(rivals)}|positive_rivals={len(positive)}"
            f"|row_math={row_math}|total_math={total_math}"
            f"|company={totals.get('company_unit')}"
            f"|competitor={totals.get('competitor_unit')}"
            f"|market={totals.get('market_unit')}"
        )

    rep_ims_id, rep_production_id = PersistentRepresentativeSnapshotService.source_identity(2026, 8)
    sets = db.session.execute(
        sa.select(
            representative_snapshot_sets.c.id,
            representative_snapshot_sets.c.source_upload_id,
            representative_snapshot_sets.c.production_upload_id,
            representative_snapshot_sets.c.status,
            representative_snapshot_sets.c.representative_count,
        ).where(
            representative_snapshot_sets.c.year == 2026,
            representative_snapshot_sets.c.month == 8,
        ).order_by(representative_snapshot_sets.c.id.desc())
    ).all()
    print(f"REP_SOURCE|ims_id={rep_ims_id}|production_id={rep_production_id}|sets={len(sets)}")
    for set_row in sets[:8]:
        row_count = int(db.session.execute(
            sa.select(sa.func.count()).select_from(representative_snapshots).where(
                representative_snapshots.c.set_id == int(set_row.id)
            )
        ).scalar() or 0)
        print(
            f"REP_SET|id={set_row.id}|source={set_row.source_upload_id}"
            f"|production={set_row.production_upload_id}|status={set_row.status}"
            f"|declared={set_row.representative_count}|rows={row_count}"
        )
        if int(set_row.source_upload_id) != int(rep_ims_id) or row_count == 0:
            continue
        raw_rows = db.session.execute(
            sa.select(representative_snapshots.c.payload_json).where(
                representative_snapshots.c.set_id == int(set_row.id)
            )
        ).scalars().all()
        seven_rows = upload_45 = coherent = travazol_named = 0
        for raw in raw_rows:
            try:
                snap = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            market = ((((snap.get("snapshots") or {}).get("monthly") or {}).get("market_analysis")) or {})
            rows = market.get("rows") or []
            totals = market.get("totals") or {}
            if len(rows) == 7:
                seven_rows += 1
            if int(market.get("upload_id") or 0) == int(rep_ims_id):
                upload_45 += 1
            if len(rows) == 7 and all(
                abs(float(row.get("actual_unit") or 0) + float(row.get("competitor_unit") or 0) - float(row.get("market_unit") or 0)) <= 0.01
                for row in rows
            ) and abs(float(totals.get("actual_unit") or 0) + float(totals.get("competitor_unit") or 0) - float(totals.get("market_unit") or 0)) <= 0.01:
                coherent += 1
            travazol = next((row for row in rows if str(row.get("product_name") or "").upper() == "TRAVAZOL"), {})
            rivals = travazol.get("rivals") or []
            if rivals and all(str(r.get("name") or "").strip() and float(r.get("unit") or 0) > 0 for r in rivals):
                travazol_named += 1
        print(
            f"REP_SET_DIAG|id={set_row.id}|seven_rows={seven_rows}|upload45={upload_45}"
            f"|coherent={coherent}|travazol_named={travazol_named}|total={len(raw_rows)}"
        )
