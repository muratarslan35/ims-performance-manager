"""Resolve persisted KPI region authority rows for compact region keys.

KPI workbooks persist region aggregate controls with labels such as
``101 ISTANBUL`` while the live RegionMarketService uses compact keys such as
``101``.  The single-source reader originally required an exact territory match,
so NATIONAL reads were canonical but region reads silently fell back to legacy
mixed detail data.  This wrapper fixes only that identity mismatch.
"""
from __future__ import annotations

import re

from app.models import CompetitionData
from app.services.kpi_market_single_source import (
    AUTHORITY_PREFIX,
    _authority,
    _latest_authority_upload,
    normalize_region_payload,
)


def _region_code(value) -> str:
    match = re.match(r"^\s*(\d{3})(?:\s|$)", str(value or ""))
    return match.group(1) if match else ""


def _resolve_authority_territory(upload_id: int, region_key) -> str | None:
    """Return the unique persisted territory for a compact three-digit key."""
    code = _region_code(region_key)
    if not code:
        return None

    territories = [
        str(value)
        for (value,) in (
            CompetitionData.query.with_entities(CompetitionData.territory)
            .filter(
                CompetitionData.upload_id == int(upload_id),
                CompetitionData.sheet_name.like(f"{AUTHORITY_PREFIX}%"),
                CompetitionData.metric_type == "UNIT",
                CompetitionData.territory.like(f"{code}%"),
            )
            .distinct()
            .all()
        )
        if value
    ]
    exact = [value for value in territories if value == code]
    if len(exact) == 1:
        return exact[0]

    prefixed = [value for value in territories if _region_code(value) == code]
    unique = sorted(set(prefixed))
    if len(unique) == 1:
        return unique[0]
    if len(unique) > 1:
        raise RuntimeError(
            f"Ambiguous KPI region authority for {region_key}: {unique}"
        )
    return None


def install_kpi_region_authority_resolver() -> None:
    from app.services.region_market_service import RegionMarketService

    if getattr(RegionMarketService, "_kpi_region_authority_resolver_installed", False):
        return

    original = RegionMarketService.build

    def build_with_region_authority(self):
        payload = original(self)
        if payload.get("market_share_source") == "IMS_KPI_AGGREGATE_PAZAR":
            return payload

        upload = _latest_authority_upload(self.year, self.month)
        if upload is None:
            return payload
        territory = _resolve_authority_territory(upload.id, self.region_key)
        if territory is None:
            return payload
        controls = _authority(upload.id, territory)
        if not controls:
            return payload

        normalize_region_payload(payload, controls, self._display_integer)
        payload["upload_id"] = int(upload.id)
        payload["authority_territory"] = territory
        return payload

    RegionMarketService._kpi_region_authority_resolver_original_build = original
    RegionMarketService.build = build_with_region_authority
    RegionMarketService._kpi_region_authority_resolver_installed = True
