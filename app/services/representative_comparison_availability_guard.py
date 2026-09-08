"""Mark representative month comparisons when previous rival data is unavailable.

Company actuals keep using the canonical P2 > P1 > IMS result. Rival comparison
is a separate source contract: if the previous month contains no rival output at
all, current-month rival boxes must not be compared against an invented zero.
"""
from __future__ import annotations

from app.services.representative_market_service import RepresentativeMarketService


def install_representative_comparison_availability_guard() -> None:
    if getattr(RepresentativeMarketService, "_comparison_availability_guard_installed", False):
        return

    original_build = RepresentativeMarketService.build

    def guarded_build(self):
        payload = original_build(self)
        rows = payload.get("rows") or []
        if not rows:
            return payload

        # Previous rival source availability is month/scope-wide. A month with
        # no rival rows must not be interpreted as seven genuine zero values.
        previous_rival_available = any(
            abs(float(row.get("previous_competitor_unit") or 0.0)) > 0.0
            for row in rows
        )

        for row in rows:
            row["previous_competitor_available"] = previous_rival_available
            if not previous_rival_available:
                # Keep company previous-month actual and its company delta intact.
                # Only rival change/signal becomes unavailable until rival data arrives.
                row["competitor_change_unit"] = 0.0

        payload["previous_competitor_available"] = previous_rival_available
        return payload

    RepresentativeMarketService.build = guarded_build
    RepresentativeMarketService._comparison_availability_guard_installed = True
