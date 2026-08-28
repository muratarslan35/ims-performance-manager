"""Targeted read-path repair for the Week-8 field regressions.

This module intentionally changes no import, target, prime or dashboard formula.
It only makes field-facing reads use the already persisted IMS realization values
on ``Target`` when the period has a completed IMS upload. Production precedence
remains P2 > P1 > IMS and numeric zero remains a valid realization.
"""
from __future__ import annotations

import re
from decimal import Decimal

from flask import g, has_request_context
from sqlalchemy import exists

from app.extensions import db
from app.models import CompetitionData, IMSUpload, Target


_MONTH_DIMENSION = re.compile(
    r"^(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+\d{4}$",
    re.IGNORECASE,
)


def _has_completed_ims(year: int, month: int) -> bool:
    return db.session.query(IMSUpload.id).filter(
        IMSUpload.year == int(year),
        IMSUpload.month == int(month),
        IMSUpload.status == "COMPLETED",
    ).limit(1).scalar() is not None


def _apply_target_ims_actuals(rows, targets, *, has_completed_ims: bool):
    """Replace only IMS fallback values with the import-populated target actuals."""
    if not has_completed_ims:
        return rows
    target_by_product = {int(item.product_id): item for item in targets}
    for product_id, values in list((rows or {}).items()):
        if values.get("source") != "IMS":
            continue
        target = target_by_product.get(int(product_id))
        if target is None:
            continue
        actual_tl = Decimal(str(target.tl_realization or 0))
        actual_unit = Decimal(str(target.unit_realization or 0))
        target_tl = Decimal(str(values.get("target_tl") or target.tl_target or 0))
        repaired = dict(values)
        repaired.update(
            complete=True,
            actual_tl=actual_tl,
            actual_unit=actual_unit,
            realization_percent=(actual_tl * Decimal("100") / target_tl) if target_tl else Decimal("0"),
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
        if not rows:
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
        )

    def effective_product(cls, year, month, representative_id, product_id):
        if has_request_context():
            cache = getattr(g, "_week8_effective_product_batches", None)
            if cache is None:
                cache = {}
                g._week8_effective_product_batches = cache
            key = (int(year), int(month), int(representative_id))
            if key not in cache:
                cache[key] = cls.effective_products(year, month, representative_id)
            if int(product_id) in cache[key]:
                return cache[key][int(product_id)]

        row = original_effective_product(cls, year, month, representative_id, product_id)
        if row.get("source") != "IMS" or not _has_completed_ims(year, month):
            return row
        target = Target.query.filter_by(
            year=int(year), month=int(month), representative_id=int(representative_id), product_id=int(product_id)
        ).first()
        if target is None:
            return row
        actual_tl = Decimal(str(target.tl_realization or 0))
        actual_unit = Decimal(str(target.unit_realization or 0))
        target_tl = Decimal(str(row.get("target_tl") or target.tl_target or 0))
        repaired = dict(row)
        repaired.update(
            complete=True,
            actual_tl=actual_tl,
            actual_unit=actual_unit,
            realization_percent=(actual_tl * Decimal("100") / target_tl) if target_tl else Decimal("0"),
        )
        return repaired

    ProductionResultService.effective_products = classmethod(effective_products)
    ProductionResultService.effective_product = classmethod(effective_product)

    original_market_build = RepresentativeMarketService.build

    def repaired_market_build(self):
        payload = original_market_build(self)
        resolved = ProductionResultService.effective_products(self.year, self.month, self.representative.id)
        for item in payload.get("rows", []):
            product = item.get("product")
            product_id = getattr(product, "id", None)
            effective = resolved.get(int(product_id)) if product_id is not None else None
            if not effective or effective.get("actual_unit") is None:
                continue
            actual_unit = float(effective.get("actual_unit") or 0)
            market_unit = float(item.get("market_unit") or 0)
            competitor_unit = max(market_unit - actual_unit, 0.0)
            item["actual_unit"] = round(actual_unit, 2)
            item["competitor_unit"] = round(competitor_unit, 2)
            item["share_percent"] = round(actual_unit * 100.0 / market_unit, 1) if market_unit else 0.0
            item["gap_unit"] = round(competitor_unit - actual_unit, 2)
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

    # Keep the safe PR-285 region-period optimization, but not its broad field
    # monkeypatches. This query is upload-centered and avoids DISTINCT scans
    # across the multi-million-row competition table.
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
