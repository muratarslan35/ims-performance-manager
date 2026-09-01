"""Bound region-detail P2/P1/IMS reads to one request-local snapshot.

The legacy region report calculates monthly/3-month/6-month/yearly windows from
mostly the same representative/product periods.  Its aggregate loop historically
called ``effective_product`` (and, for production rows, ``final_product_result``)
for every cell.  That turns one region page into hundreds/thousands of repeated
SQLite lookups.

This optimizer keeps all business semantics in ``RegionPerformanceService`` but
pre-resolves the exact target cells for the requested window with four bounded
queries (targets, IMS summaries, production uploads, production rows).  During
that aggregate call only, ContextVar-backed wrappers serve the existing service
APIs from the snapshot.  There is no process-global stale data cache and no
cross-request mutation, so P2 > P1 > IMS and numeric-zero semantics stay intact.
"""

from collections import defaultdict
from contextvars import ContextVar
from decimal import Decimal

from sqlalchemy import and_, func, or_

from app.extensions import db
from app.models import IMSSummary, ProductionResult, ProductionResultUpload, Target
from app.services.production_result_service import ProductionResultService
from app.services.region_performance_service import RegionPerformanceService


_REGION_SNAPSHOT = ContextVar("region_performance_source_snapshot", default=None)
_INSTALLED = False


def _month_conditions(model, months):
    return [and_(model.year == year, model.month == month) for year, month in months]


def _d(value):
    return Decimal(str(value or 0))


def _build_snapshot(service, months):
    months = tuple((int(year), int(month)) for year, month in months)
    rep_ids = tuple(int(item) for item in service.rep_ids)
    if not months or not rep_ids:
        return {
            "effective": {},
            "production_result": {},
            "uploads_by_period": {},
        }

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
    if not target_by_key:
        return {
            "effective": {},
            "production_result": {},
            "uploads_by_period": {},
        }

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
        "effective": effective,
        "production_result": selected_production,
        "uploads_by_period": dict(uploads_by_period),
    }


def install_region_performance_bulk_optimizer():
    """Install request-local batch resolution without changing public APIs."""
    global _INSTALLED
    if _INSTALLED:
        return

    original_aggregate = RegionPerformanceService.aggregate
    original_effective_product = ProductionResultService.effective_product
    original_final_product_result = ProductionResultService.final_product_result
    original_applied_uploads = ProductionResultService.applied_uploads

    def aggregate(self, months):
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
        if snapshot is not None:
            period = (int(year), int(month))
            if period in snapshot["uploads_by_period"]:
                return list(snapshot["uploads_by_period"][period])
            # The snapshot is authoritative for every requested report month;
            # an absent period therefore means there is no applied production.
            return []
        return original_applied_uploads(year, month)

    RegionPerformanceService.aggregate = aggregate
    ProductionResultService.effective_product = classmethod(effective_product)
    ProductionResultService.final_product_result = classmethod(final_product_result)
    ProductionResultService.applied_uploads = classmethod(applied_uploads)
    _INSTALLED = True
