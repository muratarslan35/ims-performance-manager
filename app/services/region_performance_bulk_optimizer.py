"""Bound region-detail P2/P1/IMS reads to one request-local snapshot.

The legacy region report calculates monthly/3-month/6-month/yearly windows from
mostly the same representative/product periods. Its aggregate loop historically
called ``effective_product`` (and, for production rows, ``final_product_result``)
for every cell, and ``report`` repeated those overlapping windows independently.

This optimizer keeps all business semantics in ``RegionPerformanceService`` but
pre-resolves the report year with four bounded source queries (targets, IMS
summaries, production uploads, production rows). Monthly/3/6/yearly KPI windows
and the annual chart then reuse that same request-local ContextVar snapshot.
There is no process-global stale cache and no cross-request mutation, so
P2 > P1 > IMS and numeric-zero semantics stay intact.
"""

from collections import defaultdict
from contextvars import ContextVar
from decimal import Decimal

from sqlalchemy import and_, func, or_

from app.extensions import db
from app.models import IMSSummary, Product, ProductionResult, ProductionResultUpload, Target
from app.services.production_result_service import ProductionResultService
from app.services.region_performance_service import RegionPerformanceService
from app.services.tl_box_calculation_service import TLBoxCalculationService


_REGION_SNAPSHOT = ContextVar("region_performance_source_snapshot", default=None)
_INSTALLED = False


def _month_conditions(model, months):
    return [and_(model.year == year, model.month == month) for year, month in months]


def _d(value):
    return Decimal(str(value or 0))


def _empty_snapshot(months):
    return {
        "periods": set(months),
        "effective": {},
        "production_result": {},
        "uploads_by_period": {},
    }


def _build_snapshot(service, months):
    months = tuple(sorted({(int(year), int(month)) for year, month in months}))
    rep_ids = tuple(int(item) for item in service.rep_ids)
    if not months or not rep_ids:
        return _empty_snapshot(months)

    target_rows = db.session.query(
        Target.year,
        Target.month,
        Target.representative_id,
        Target.product_id,
        func.coalesce(func.sum(Target.tl_target), 0.0),
        func.coalesce(func.sum(Target.unit_target), 0.0),
    ).filter(
        Target.representative_id.in_(rep_ids),
        or_(*_month_conditions(Target, months)),
    ).group_by(
        Target.year,
        Target.month,
        Target.representative_id,
        Target.product_id,
    ).all()

    target_by_key = {
        (int(year), int(month), int(rep_id), int(product_id)): (_d(target_tl), _d(target_unit))
        for year, month, rep_id, product_id, target_tl, target_unit in target_rows
    }

    uploads = ProductionResultUpload.query.filter(
        ProductionResultUpload.status == ProductionResultUpload.STATUS_APPLIED,
        or_(*_month_conditions(ProductionResultUpload, months)),
    ).order_by(
        ProductionResultUpload.year.asc(),
        ProductionResultUpload.month.asc(),
        ProductionResultUpload.production_stage.desc(),
        ProductionResultUpload.applied_at.desc(),
        ProductionResultUpload.id.desc(),
    ).all()
    uploads_by_period = defaultdict(list)
    for upload in uploads:
        uploads_by_period[(int(upload.year), int(upload.month))].append(upload)

    if not target_by_key:
        snapshot = _empty_snapshot(months)
        snapshot["uploads_by_period"] = dict(uploads_by_period)
        return snapshot

    product_ids = {key[3] for key in target_by_key}
    summary_rows = IMSSummary.query.filter(
        IMSSummary.representative_id.in_(rep_ids),
        IMSSummary.product_id.in_(product_ids),
        or_(*_month_conditions(IMSSummary, months)),
    ).all()
    summary_by_key = {
        (int(row.year), int(row.month), int(row.representative_id), int(row.product_id)): row
        for row in summary_rows
    }
    product_prices = {
        int(row.id): row.unit_price
        for row in Product.query.filter(Product.id.in_(product_ids)).all()
    }

    upload_ids = [int(upload.id) for upload in uploads]
    production_rows = []
    if upload_ids:
        production_rows = ProductionResult.query.filter(
            ProductionResult.upload_id.in_(upload_ids),
            ProductionResult.representative_id.in_(rep_ids),
            ProductionResult.product_id.in_(product_ids),
        ).all()
    production_by_key = {
        (int(row.upload_id), int(row.representative_id), int(row.product_id)): row
        for row in production_rows
    }

    effective = {}
    selected_production = {}
    for key, (target_tl, target_unit) in target_by_key.items():
        year, month, representative_id, product_id = key
        selected_upload = None
        selected_result = None
        for upload in uploads_by_period.get((year, month), ()):  # P2 -> P1 ordering above.
            candidate = production_by_key.get(
                (int(upload.id), representative_id, product_id)
            )
            if candidate is not None:
                selected_upload = upload
                selected_result = candidate
                break

        if selected_result is not None:
            percent = (
                _d(selected_result.actual_tl) * Decimal("100") / target_tl
                if target_tl and selected_result.actual_tl is not None
                else _d(selected_result.realization_percent)
            )
            actual_tl = (
                _d(selected_result.actual_tl)
                if selected_result.actual_tl is not None
                else target_tl * percent / Decimal("100")
            )
            actual_unit = (
                _d(selected_result.actual_unit)
                if selected_result.actual_unit is not None
                else target_unit * percent / Decimal("100")
            )
            effective[key] = {
                "source": f"PRODUCTION_{selected_upload.production_stage}",
                "complete": True,
                "target_tl": target_tl,
                "target_unit": target_unit,
                "realization_percent": percent,
                "actual_tl": actual_tl,
                "actual_unit": actual_unit,
            }
            selected_production[key] = selected_result
            continue

        summary = summary_by_key.get(key)
        actual_tl = _d(summary.tl if summary else 0)
        if TLBoxCalculationService.applies(year, month):
            target_unit = TLBoxCalculationService.boxes_from_tl(target_tl, product_prices.get(product_id))
            actual_unit = TLBoxCalculationService.boxes_from_tl(actual_tl, product_prices.get(product_id))
        else:
            actual_unit = _d(summary.unit if summary else 0)
        effective[key] = {
            "source": "IMS",
            "complete": summary is not None,
            "target_tl": target_tl,
            "target_unit": target_unit,
            "realization_percent": (
                actual_tl / target_tl * Decimal("100") if target_tl else Decimal("0")
            ),
            "actual_tl": actual_tl,
            "actual_unit": actual_unit,
        }

    return {
        "periods": set(months),
        "effective": effective,
        "production_result": selected_production,
        "uploads_by_period": dict(uploads_by_period),
    }


def install_region_performance_bulk_optimizer():
    """Install one bounded request-local source snapshot for every region report."""
    global _INSTALLED
    if _INSTALLED:
        return

    original_report = RegionPerformanceService.report
    original_aggregate = RegionPerformanceService.aggregate
    original_effective_product = ProductionResultService.effective_product
    original_final_product_result = ProductionResultService.final_product_result
    original_applied_uploads = ProductionResultService.applied_uploads

    def report(self):
        # Include the full selected year because the same report renders a
        # 12-month realization chart after its monthly/3/6/yearly KPI windows.
        months = {(self.year, month) for month in range(1, 13)}
        for _, _, length in self.PERIODS:
            months.update(self.period_months(length))
        snapshot = _build_snapshot(self, months)
        token = _REGION_SNAPSHOT.set(snapshot)
        try:
            return original_report(self)
        finally:
            _REGION_SNAPSHOT.reset(token)

    def aggregate(self, months):
        # report() already owns the widest snapshot. Keep direct aggregate()
        # callers optimized too, but never rebuild inside the same report.
        if _REGION_SNAPSHOT.get() is not None:
            return original_aggregate(self, months)
        snapshot = _build_snapshot(self, months)
        token = _REGION_SNAPSHOT.set(snapshot)
        try:
            return original_aggregate(self, months)
        finally:
            _REGION_SNAPSHOT.reset(token)

    def effective_product(cls, year, month, representative_id, product_id):
        snapshot = _REGION_SNAPSHOT.get()
        if snapshot is not None:
            key = (int(year), int(month), int(representative_id), int(product_id))
            row = snapshot["effective"].get(key)
            if row is not None:
                return row
        return original_effective_product(year, month, representative_id, product_id)

    def final_product_result(cls, year, month, representative_id, product_id):
        snapshot = _REGION_SNAPSHOT.get()
        if snapshot is not None:
            key = (int(year), int(month), int(representative_id), int(product_id))
            if key in snapshot["effective"]:
                return snapshot["production_result"].get(key)
        return original_final_product_result(year, month, representative_id, product_id)

    def applied_uploads(cls, year, month):
        snapshot = _REGION_SNAPSHOT.get()
        period = (int(year), int(month))
        if snapshot is not None and period in snapshot["periods"]:
            return list(snapshot["uploads_by_period"].get(period, ()))
        return original_applied_uploads(year, month)

    RegionPerformanceService.report = report
    RegionPerformanceService.aggregate = aggregate
    ProductionResultService.effective_product = classmethod(effective_product)
    ProductionResultService.final_product_result = classmethod(final_product_result)
    ProductionResultService.applied_uploads = classmethod(applied_uploads)
    _INSTALLED = True
