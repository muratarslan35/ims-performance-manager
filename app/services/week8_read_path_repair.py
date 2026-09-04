"""Targeted read-path repair for the Week-8 field regressions.

This module intentionally changes no import, target, prime or dashboard formula.
Only representative and region detail requests may use the already persisted IMS
realization values on ``Target`` when the summary read is missing/corrupt.
Production precedence remains P2 > P1 > IMS and numeric zero remains valid.
"""
from __future__ import annotations

import re
from decimal import Decimal

from flask import g, has_request_context, request
from sqlalchemy import exists

from app.extensions import db
from app.models import CompetitionData, IMSUpload, Product, Target
from app.services.tl_box_calculation_service import TLBoxCalculationService


_MONTH_DIMENSION = re.compile(
    r"^(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+\d{4}$",
    re.IGNORECASE,
)


def _is_field_detail_request() -> bool:
    if not has_request_context():
        return False
    path = str(request.path or "")
    return path.startswith("/representatives/view/") or path.startswith("/regions/")


def _is_representative_detail_request() -> bool:
    return has_request_context() and str(request.path or "").startswith("/representatives/view/")


def _has_completed_ims(year: int, month: int) -> bool:
    return db.session.query(IMSUpload.id).filter(
        IMSUpload.year == int(year),
        IMSUpload.month == int(month),
        IMSUpload.status == "COMPLETED",
    ).limit(1).scalar() is not None


def _apply_target_ims_actuals(
    rows,
    targets,
    *,
    has_completed_ims: bool,
    year: int | None = None,
    month: int | None = None,
):
    """Repair only IMS rows where target realization is the safer persisted source.

    Older fixtures/data can have a valid summary while target realization fields
    are still zero. Those rows remain untouched. A non-zero target realization,
    or a missing/zero summary for a completed IMS period, is safe to resolve from
    Target. This keeps genuine zero while avoiding Week-8's zero-TL/million-unit
    corrupted summaries.

    From April 2026 onward the canonical IMS box authority is TL / unit price.
    The Week-8 repair must therefore never restore the legacy persisted
    ``Target.unit_realization`` value over a TL-derived box result.
    """
    if not has_completed_ims:
        return rows
    target_by_product = {int(item.product_id): item for item in targets}
    use_tl_boxes = (
        year is not None
        and month is not None
        and TLBoxCalculationService.applies(int(year), int(month))
    )
    product_prices = {}
    if use_tl_boxes and target_by_product:
        product_prices = {
            int(product_id): unit_price
            for product_id, unit_price in db.session.query(Product.id, Product.unit_price).filter(
                Product.id.in_(target_by_product.keys())
            ).all()
        }

    for product_id, values in list((rows or {}).items()):
        if values.get("source") != "IMS":
            continue
        target = target_by_product.get(int(product_id))
        if target is None:
            continue

        target_actual_tl = Decimal(str(target.tl_realization or 0))
        target_actual_unit = Decimal(str(target.unit_realization or 0))
        current_tl = Decimal(str(values.get("actual_tl") or 0))
        current_unit = Decimal(str(values.get("actual_unit") or 0))
        target_has_actual = target_actual_tl != 0 or target_actual_unit != 0
        current_has_actual = current_tl != 0 or current_unit != 0

        # Legacy/fixture summaries with real values and untouched target actuals
        # remain authoritative. Week-8 has populated target actuals, so it enters
        # the repair path even though its summary contains bad values.
        if current_has_actual and not target_has_actual and values.get("complete"):
            continue

        target_tl = Decimal(str(values.get("target_tl") or target.tl_target or 0))
        repaired_actual_unit = (
            TLBoxCalculationService.boxes_from_tl(
                target_actual_tl,
                product_prices.get(int(product_id)),
            )
            if use_tl_boxes
            else target_actual_unit
        )
        repaired = dict(values)
        repaired.update(
            complete=True,
            actual_tl=target_actual_tl,
            actual_unit=repaired_actual_unit,
            realization_percent=(target_actual_tl * Decimal("100") / target_tl) if target_tl else Decimal("0"),
        )
        rows[int(product_id)] = repaired
    return rows


def _is_period_dimension(row) -> bool:
    group = str(getattr(row, "product_group", "") or "").strip().upper()
    product = str(getattr(row, "product_name", "") or "").strip().upper()
    return group == "MONTH" or bool(_MONTH_DIMENSION.fullmatch(product))


def install_week8_read_path_repair() -> None:
    """Install narrowly-scoped read repairs once per process."""
    from app.services.dashboard_service import DashboardService
    from app.services.production_result_service import ProductionResultService
    from app.services.region_market_service import RegionMarketService
    from app.services.representative_market_service import RepresentativeMarketService

    if getattr(ProductionResultService, "_week8_read_repair_installed", False):
        return

    original_effective_products = ProductionResultService.effective_products.__func__
    original_effective_product = ProductionResultService.effective_product.__func__

    def effective_products(cls, year, month, representative_id, product_ids=None):
        rows = original_effective_products(cls, year, month, representative_id, product_ids)
        if not rows or not _is_field_detail_request():
            return rows
        product_ids_set = {int(item) for item in (product_ids or rows.keys())}
        targets = Target.query.filter(
            Target.year == int(year),
            Target.month == int(month),
            Target.representative_id == int(representative_id),
            Target.product_id.in_(product_ids_set),
        ).all()
        return _apply_target_ims_actuals(
            rows,
            targets,
            has_completed_ims=_has_completed_ims(year, month),
            year=year,
            month=month,
        )

    def effective_product(cls, year, month, representative_id, product_id):
        if not _is_field_detail_request():
            return original_effective_product(cls, year, month, representative_id, product_id)

        cache = getattr(g, "_week8_effective_product_batches", None)
        if cache is None:
            cache = {}
            g._week8_effective_product_batches = cache
        key = (int(year), int(month), int(representative_id))
        if key not in cache:
            cache[key] = cls.effective_products(year, month, representative_id)
        if int(product_id) in cache[key]:
            return cache[key][int(product_id)]
        return original_effective_product(cls, year, month, representative_id, product_id)

    ProductionResultService.effective_products = classmethod(effective_products)
    ProductionResultService.effective_product = classmethod(effective_product)

    original_market_build = RepresentativeMarketService.build

    def repaired_market_build(self):
        payload = original_market_build(self)
        if not _is_representative_detail_request():
            return payload

        resolved = ProductionResultService.effective_products(self.year, self.month, self.representative.id)
        use_tl_boxes = TLBoxCalculationService.applies(self.year, self.month)
        for item in payload.get("rows", []):
            product = item.get("product")
            product_id = getattr(product, "id", None)
            effective = resolved.get(int(product_id)) if product_id is not None else None
            if not effective or effective.get("actual_unit") is None:
                continue
            actual_unit = float(effective.get("actual_unit") or 0)
            old_market_unit = float(item.get("market_unit") or 0)
            old_actual_unit = float(item.get("actual_unit") or 0)
            old_competitor_unit = float(item.get("competitor_unit") or max(old_market_unit - old_actual_unit, 0.0))
            if use_tl_boxes and not str(effective.get("source") or "").startswith("PRODUCTION_"):
                # Rival UNIT values remain workbook-authoritative. Replace only
                # our company side with the TL-derived box result, then rebuild
                # the total market so a corrupt IMS unit cannot distort share.
                competitor_unit = max(old_competitor_unit, 0.0)
                market_unit = actual_unit + competitor_unit
            else:
                market_unit = old_market_unit
                competitor_unit = max(market_unit - actual_unit, 0.0)
            item["actual_unit"] = round(actual_unit, 2)
            item["market_unit"] = round(market_unit, 2)
            item["competitor_unit"] = round(competitor_unit, 2)
            item["share_percent"] = round(actual_unit * 100.0 / market_unit, 1) if market_unit else 0.0
            item["gap_unit"] = round(competitor_unit - actual_unit, 2)
            if effective.get("target_unit") is not None:
                item["target_unit"] = round(float(effective.get("target_unit") or 0), 2)
            item["realization_percent"] = float(effective.get("realization_percent") or 0)
            item["realization_source"] = effective.get("source", "IMS")
            item["attention"] = (
                "critical" if competitor_unit > actual_unit * 1.5 and competitor_unit > 0
                else "warning" if competitor_unit > actual_unit
                else "strong"
            )

        payload["chart_rows"] = [
            {
                "product_name": item["product"].product_name,
                "actual_unit": item.get("actual_unit", 0),
                "competitor_unit": item.get("competitor_unit", 0),
            }
            for item in payload.get("rows", [])
        ]
        total_actual = sum(float(item.get("actual_unit") or 0) for item in payload.get("rows", []))
        total_market = sum(float(item.get("market_unit") or 0) for item in payload.get("rows", []))
        payload["totals"] = {
            "actual_unit": round(total_actual, 2),
            "market_unit": round(total_market, 2),
            "competitor_unit": round(max(total_market - total_actual, 0.0), 2),
            "share_percent": round(total_actual * 100.0 / total_market, 1) if total_market else 0.0,
        }
        return payload

    RepresentativeMarketService.build = repaired_market_build

    # Preserve only the proven safe region-period optimization from PR #285.
    def bounded_available_periods(self):
        prefix = f"{self.region_key}%"
        has_scope = exists().where(
            CompetitionData.upload_id == IMSUpload.id,
            CompetitionData.metric_type == "UNIT",
            CompetitionData.territory.like(prefix),
        )
        rows = db.session.query(IMSUpload.year, IMSUpload.month).filter(
            IMSUpload.status == "COMPLETED",
            has_scope,
        ).distinct().order_by(IMSUpload.year.desc(), IMSUpload.month.desc()).all()
        return [
            {"year": int(year), "month": int(month), "label": f"{int(month):02d}/{int(year)}"}
            for year, month in rows
        ]

    RegionMarketService._available_periods = bounded_available_periods

    original_competitor_ai = DashboardService._competitor_ai

    def competitor_ai(rows, product_rows):
        # PAZAR sheets may contain a period axis (e.g. FEB 2026 / MONTH).
        # It is a dimension label, never a competitor product.
        return original_competitor_ai(
            [row for row in (rows or []) if not _is_period_dimension(row)],
            product_rows,
        )

    DashboardService._competitor_ai = staticmethod(competitor_ai)
    ProductionResultService._week8_read_repair_installed = True
