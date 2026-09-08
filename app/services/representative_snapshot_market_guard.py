"""Keep representative snapshots on the canonical box/market contract.

The historical representative-market repair is request-scoped because it was
originally introduced for the detail route. Persistent representative snapshots
are built by the background worker without a Flask request, so legacy IMS unit
fields can leak into that stored read model. This adapter is intentionally a
read-only repair and activates only when the market payload actually disagrees
with the canonical P2 > P1 > IMS result. Existing market semantics are otherwise
left untouched.
"""
from __future__ import annotations

from app.services.production_result_service import ProductionResultService
from app.services.representative_market_service import RepresentativeMarketService


def _product_id(row):
    product = row.get("product") if isinstance(row, dict) else None
    value = getattr(product, "id", None)
    return int(value) if value is not None else None


def _named_rival_total(row):
    rivals = row.get("rivals") or []
    if not rivals:
        return None
    return sum(float(item.get("unit") or 0.0) for item in rivals)


def _canonical_competitor(row, actual_unit):
    """Keep workbook rival/market authority while replacing only own boxes."""
    named_total = _named_rival_total(row)
    if named_total is not None:
        return max(float(named_total), 0.0)

    market_unit = float(row.get("market_unit") or 0.0)
    if market_unit >= float(actual_unit):
        return max(market_unit - float(actual_unit), 0.0)

    return max(float(row.get("competitor_unit") or 0.0), 0.0)


def _canonical_actual(row, effective):
    if effective and effective.get("actual_unit") is not None:
        return float(effective.get("actual_unit") or 0.0)
    return float(row.get("actual_unit") or 0.0)


def _has_previous(row, effective):
    if effective and bool(effective.get("complete")):
        return True
    if not row:
        return False
    return bool(
        row.get("has_previous")
        or float(row.get("actual_unit") or 0.0)
        or float(row.get("market_unit") or 0.0)
        or float(row.get("competitor_unit") or 0.0)
        or (row.get("rivals") or [])
    )


def _needs_canonical_repair(rows, effective_by_product):
    """Detect the exact stale-snapshot defect without rewriting healthy reads."""
    for row in rows:
        product_id = _product_id(row)
        if product_id is None:
            continue
        effective = effective_by_product.get(product_id)
        if not effective or not bool(effective.get("complete")):
            continue
        canonical_actual = effective.get("actual_unit")
        if canonical_actual is not None and abs(
            float(row.get("actual_unit") or 0.0) - float(canonical_actual or 0.0)
        ) >= 0.5:
            return True
        canonical_target = effective.get("target_unit")
        if canonical_target is not None and abs(
            float(row.get("target_unit") or 0.0) - float(canonical_target or 0.0)
        ) >= 0.5:
            return True
    return False


def install_representative_snapshot_market_guard() -> None:
    """Repair only representative market payloads that contain canonical drift."""
    if getattr(RepresentativeMarketService, "_snapshot_market_guard_installed", False):
        return

    original_build = RepresentativeMarketService.build

    def guarded_build(self):
        payload = original_build(self)
        rows = payload.get("rows", [])
        if not rows:
            return payload

        current_effective = ProductionResultService.effective_products(
            self.year, self.month, self.representative.id
        )
        if not _needs_canonical_repair(rows, current_effective):
            return payload

        previous_year = self.year if self.month > 1 else self.year - 1
        previous_month = self.month - 1 if self.month > 1 else 12
        previous_effective = ProductionResultService.effective_products(
            previous_year, previous_month, self.representative.id
        )

        # Resolve the previous month through the captured pre-guard builder so
        # its own period/brick scope is used without recursively entering here.
        previous_service = RepresentativeMarketService(
            self.representative, previous_year, previous_month
        )
        previous_payload = original_build(previous_service)
        previous_rows = {
            product_id: row
            for row in previous_payload.get("rows", [])
            if (product_id := _product_id(row)) is not None
        }

        for row in rows:
            product_id = _product_id(row)
            if product_id is None:
                continue

            effective = current_effective.get(product_id)
            actual_unit = _canonical_actual(row, effective)
            competitor_unit = _canonical_competitor(row, actual_unit)
            market_unit = actual_unit + competitor_unit

            previous_row = previous_rows.get(product_id, {})
            previous_result = previous_effective.get(product_id)
            previous_actual = _canonical_actual(previous_row, previous_result)
            previous_competitor = _canonical_competitor(previous_row, previous_actual)
            has_previous = _has_previous(previous_row, previous_result)

            actual_change = actual_unit - previous_actual
            competitor_change = competitor_unit - previous_competitor
            actual_change_percent = (
                actual_change * 100.0 / previous_actual if previous_actual else None
            )

            row["actual_unit"] = round(actual_unit, 2)
            row["competitor_unit"] = round(competitor_unit, 2)
            row["market_unit"] = round(market_unit, 2)
            row["share_percent"] = (
                round(actual_unit * 100.0 / market_unit, 1) if market_unit else 0.0
            )
            row["gap_unit"] = round(competitor_unit - actual_unit, 2)
            row["has_previous"] = has_previous
            row["previous_actual_unit"] = round(previous_actual, 2)
            row["previous_competitor_unit"] = round(previous_competitor, 2)
            row["actual_change_unit"] = round(actual_change, 2)
            row["competitor_change_unit"] = round(competitor_change, 2)
            row["actual_change_percent"] = (
                round(actual_change_percent, 1)
                if actual_change_percent is not None
                else None
            )
            if effective:
                if effective.get("target_unit") is not None:
                    row["target_unit"] = round(
                        float(effective.get("target_unit") or 0.0), 2
                    )
                row["realization_percent"] = float(
                    effective.get("realization_percent") or 0.0
                )
                row["realization_source"] = effective.get("source", "IMS")
            row["attention"] = (
                "critical"
                if competitor_unit > actual_unit * 1.5 and competitor_unit > 0
                else "warning"
                if competitor_unit > actual_unit
                else "strong"
            )

        payload["chart_rows"] = [
            {
                "product_name": row["product"].product_name,
                "actual_unit": float(row.get("actual_unit") or 0.0),
                "competitor_unit": float(row.get("competitor_unit") or 0.0),
            }
            for row in rows
        ]
        total_actual = sum(float(row.get("actual_unit") or 0.0) for row in rows)
        total_competitor = sum(
            float(row.get("competitor_unit") or 0.0) for row in rows
        )
        total_market = total_actual + total_competitor
        payload["totals"] = {
            "actual_unit": round(total_actual, 2),
            "competitor_unit": round(total_competitor, 2),
            "market_unit": round(total_market, 2),
            "share_percent": (
                round(total_actual * 100.0 / total_market, 1) if total_market else 0.0
            ),
        }
        return payload

    RepresentativeMarketService._snapshot_market_guard_original_build = original_build
    RepresentativeMarketService.build = guarded_build
    RepresentativeMarketService._snapshot_market_guard_installed = True
