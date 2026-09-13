from app import create_app
from app.services.persistent_region_snapshot_service import PersistentRegionSnapshotService
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
