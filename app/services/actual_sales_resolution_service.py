"""Accepted realization source resolution layer.

Production files provide authoritative realization percentages, not reconstructed
sales TL. Do not infer or clamp production percentages. A value such as 230%
is a valid final company result and must remain 230%.

Period source priority is availability based and never waits:
    PRODUCTION_2 > PRODUCTION_1 > IMS

BOŞ/BOS rows are ordinary business rows and must not be filtered here.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Iterable, Mapping, Optional


class ActualSource(str, Enum):
    IMS = "IMS"
    PRODUCTION_1 = "PRODUCTION_1"
    PRODUCTION_2 = "PRODUCTION_2"


SOURCE_PRIORITY = {
    ActualSource.IMS: 10,
    ActualSource.PRODUCTION_1: 20,
    ActualSource.PRODUCTION_2: 30,
}


@dataclass(frozen=True)
class RealizationValue:
    """One immutable realization candidate for a period/business key."""

    source: ActualSource
    realization_percent: Decimal
    source_record_id: Optional[int] = None


@dataclass(frozen=True)
class ResolvedRealization:
    """Currently accepted realization and its audit provenance."""

    source: ActualSource
    realization_percent: Decimal
    source_record_id: Optional[int]


class ActualSalesResolutionService:
    """Resolve the accepted nationwide realization source for a period.

    A production workbook is a nationwide company-approved snapshot. Once an
    applied production snapshot exists, its percentages are authoritative for
    that period. Percentages are never recalculated from IMS and never capped
    at 100. If production 2 does not exist, production 1 remains final; if no
    production exists, IMS remains the current source.
    """

    @staticmethod
    def choose_period_source(available_sources: Iterable[ActualSource | str]) -> ActualSource:
        normalized = {ActualSource(source) for source in available_sources}
        if ActualSource.PRODUCTION_2 in normalized:
            return ActualSource.PRODUCTION_2
        if ActualSource.PRODUCTION_1 in normalized:
            return ActualSource.PRODUCTION_1
        if ActualSource.IMS in normalized:
            return ActualSource.IMS
        raise ValueError("Selected period has no IMS or production realization source")

    @staticmethod
    def resolve(candidates: Iterable[RealizationValue]) -> ResolvedRealization:
        values = list(candidates)
        if not values:
            raise ValueError("No realization candidate supplied")
        chosen = max(values, key=lambda item: SOURCE_PRIORITY[item.source])
        return ResolvedRealization(
            source=chosen.source,
            realization_percent=Decimal(chosen.realization_percent),
            source_record_id=chosen.source_record_id,
        )

    @staticmethod
    def resolve_nationwide_snapshot(
        rows_by_source: Mapping[ActualSource | str, Iterable[RealizationValue]],
    ) -> tuple[ActualSource, list[ResolvedRealization]]:
        """Select exactly one nationwide source; never mix IMS/production rows."""
        normalized = {ActualSource(source): list(rows) for source, rows in rows_by_source.items()}
        selected = ActualSalesResolutionService.choose_period_source(normalized.keys())
        return selected, [
            ResolvedRealization(
                source=row.source,
                realization_percent=Decimal(row.realization_percent),
                source_record_id=row.source_record_id,
            )
            for row in normalized[selected]
        ]
