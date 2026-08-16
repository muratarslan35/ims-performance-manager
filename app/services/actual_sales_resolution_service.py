"""Accepted actual-sales resolution layer.

This module intentionally does not parse production files yet. It defines the
stable business contract used by dashboards/prime calculations once production
imports are connected.

Priority is availability based, never wait based:
    PRODUCTION_2 > PRODUCTION_1 > IMS

A missing later production source never blocks an earlier accepted source.
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
class ActualSalesValue:
    """One immutable accepted-sales candidate for a period/business key."""

    source: ActualSource
    amount_tl: Decimal
    units: Optional[Decimal] = None
    source_record_id: Optional[int] = None


@dataclass(frozen=True)
class ResolvedActual:
    """The currently accepted actual value and its audit provenance."""

    source: ActualSource
    amount_tl: Decimal
    units: Optional[Decimal]
    source_record_id: Optional[int]


class ActualSalesResolutionService:
    """Resolve the latest available nationwide actual-sales source.

    Production files are nationwide snapshots. The caller first determines
    which sources exist for the selected period, then uses that single source
    consistently for Turkey/region/representative/product calculations.
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
        raise ValueError("Selected period has no IMS or production actual-sales source")

    @staticmethod
    def resolve(candidates: Iterable[ActualSalesValue]) -> ResolvedActual:
        values = list(candidates)
        if not values:
            raise ValueError("No actual-sales candidate supplied")
        chosen = max(values, key=lambda item: SOURCE_PRIORITY[item.source])
        return ResolvedActual(
            source=chosen.source,
            amount_tl=Decimal(chosen.amount_tl),
            units=None if chosen.units is None else Decimal(chosen.units),
            source_record_id=chosen.source_record_id,
        )

    @staticmethod
    def resolve_nationwide_snapshot(
        rows_by_source: Mapping[ActualSource | str, Iterable[ActualSalesValue]],
    ) -> tuple[ActualSource, list[ResolvedActual]]:
        """Select one nationwide source and return only rows from that source.

        This prevents mixing IMS and production rows inside the same accepted
        Turkey snapshot. Production import validation will be responsible for
        completeness before a production snapshot is marked accepted.
        """
        normalized = {ActualSource(source): list(rows) for source, rows in rows_by_source.items()}
        selected = ActualSalesResolutionService.choose_period_source(normalized.keys())
        return selected, [
            ResolvedActual(
                source=row.source,
                amount_tl=Decimal(row.amount_tl),
                units=None if row.units is None else Decimal(row.units),
                source_record_id=row.source_record_id,
            )
            for row in normalized[selected]
        ]
