"""Bound field-facing read paths as IMS history grows.

This module changes access paths only. Business precedence remains
P2 > P1 > IMS and numeric zero remains a valid value.
"""
from __future__ import annotations

from decimal import Decimal

from flask import g, has_request_context, request
from sqlalchemy import desc, exists, func, or_

from app.extensions import db
from app.models import (
    CompetitionData,
    IMSRawData,
    IMSUpload,
    RepresentativeBrickAssignment,
)


def _latest_completed_upload_id(year: int, month: int):
    return (
        db.session.query(IMSUpload.id)
        .filter(
            IMSUpload.year == int(year),
            IMSUpload.month == int(month),
            IMSUpload.status == "COMPLETED",
        )
        .order_by(
            desc(IMSUpload.week_number),
            desc(IMSUpload.completed_at),
            desc(IMSUpload.id),
        )
        .limit(1)
        .scalar()
    )


def _assigned_brick_names(representative_id: int, year: int, month: int):
    return [
        row[0]
        for row in db.session.query(RepresentativeBrickAssignment.brick)
        .filter_by(
            representative_id=int(representative_id),
            year=int(year),
            month=int(month),
            active=True,
        )
        .all()
        if row[0]
    ]


def _representative_brick_actuals(representative_id: int, year: int, month: int):
    upload_id = _latest_completed_upload_id(year, month)
    bricks = _assigned_brick_names(representative_id, year, month)
    if not upload_id or not bricks:
        return {}
    rows = (
        db.session.query(
            IMSRawData.product_id,
            func.coalesce(func.sum(IMSRawData.unit), 0.0),
            func.coalesce(func.sum(IMSRawData.tl), 0.0),
        )
        .filter(
            IMSRawData.upload_id == upload_id,
            IMSRawData.year == int(year),
            IMSRawData.month == int(month),
            IMSRawData.sheet_type == "brick_sales",
            IMSRawData.product_id.isnot(None),
            IMSRawData.brick.in_(bricks),
        )
        .group_by(IMSRawData.product_id)
        .all()
    )
    return {
        int(product_id): (Decimal(str(unit or 0)), Decimal(str(tl or 0)))
        for product_id, unit, tl in rows
    }


def install_field_read_runtime_optimizer() -> None:
    from app.services.production_result_service import ProductionResultService
    from app.services.representative_market_service import RepresentativeMarketService
    from app.services.region_market_service import RegionMarketService

    if getattr(ProductionResultService, "_field_read_optimizer_installed", False):
        return

    original_effective_products = ProductionResultService.effective_products.__func__

    def effective_products(cls, year, month, representative_id, product_ids=None):
        rows = original_effective_products(cls, year, month, representative_id, product_ids)
        if has_request_context() and request.endpoint == "representatives.view":
            raw_actuals = _representative_brick_actuals(representative_id, year, month)
            for product_id, values in rows.items():
                if values.get("source") != "IMS" or int(product_id) not in raw_actuals:
                    continue
                actual_unit, actual_tl = raw_actuals[int(product_id)]
                target_tl = Decimal(str(values.get("target_tl") or 0))
                values = dict(values)
                values.update(
                    source="IMS_BRICK",
                    complete=True,
                    actual_tl=actual_tl,
                    actual_unit=actual_unit,
                    realization_percent=(actual_tl * Decimal("100") / target_tl) if target_tl else Decimal("0"),
                )
                rows[int(product_id)] = values
        if has_request_context():
            cache = getattr(g, "_effective_product_batches", None)
            if cache is None:
                cache = {}
                g._effective_product_batches = cache
            cache[(int(year), int(month), int(representative_id))] = rows
        return rows

    original_effective_product = ProductionResultService.effective_product.__func__

    def effective_product(cls, year, month, representative_id, product_id):
        if has_request_context():
            cache = getattr(g, "_effective_product_batches", None)
            key = (int(year), int(month), int(representative_id))
            if cache is not None and key in cache and int(product_id) in cache[key]:
                return cache[key][int(product_id)]
            rows = cls.effective_products(year, month, representative_id)
            if int(product_id) in rows:
                return rows[int(product_id)]
        return original_effective_product(cls, year, month, representative_id, product_id)

    ProductionResultService.effective_products = classmethod(effective_products)
    ProductionResultService.effective_product = classmethod(effective_product)
    ProductionResultService._field_read_optimizer_installed = True

    def scoped_competition_rows(self, brick_keys, fallback_keys, year=None, month=None):
        year = self.year if year is None else int(year)
        month = self.month if month is None else int(month)
        upload_id = self._latest_upload_id(year, month)
        if upload_id is None:
            return None, []
        bricks = _assigned_brick_names(self.representative.id, self.year, self.month)
        scope_filters = [CompetitionData.subterritory == self.representative.rep_name]
        if bricks:
            scope_filters.append(CompetitionData.subterritory.in_(bricks))
        elif fallback_keys:
            raw_fallback = [
                value for value in (
                    self.representative.territory,
                    self.representative.city,
                    self.representative.region,
                ) if value
            ]
            if raw_fallback:
                scope_filters.append(CompetitionData.territory.in_(raw_fallback))
        rows = CompetitionData.query.filter(
            CompetitionData.upload_id == upload_id,
            CompetitionData.is_subtotal.is_(False),
            CompetitionData.is_grand_total.is_(False),
            CompetitionData.metric_type.in_(("TL", "UNIT", "MARKET_SHARE")),
            or_(*scope_filters),
        ).all()
        return upload_id, rows

    def scoped_brick_raw_rows(self, year=None, month=None):
        year = self.year if year is None else int(year)
        month = self.month if month is None else int(month)
        upload_id = self._latest_upload_id(year, month)
        bricks = _assigned_brick_names(self.representative.id, year, month)
        if upload_id is None or not bricks:
            return None, []
        rows = IMSRawData.query.filter(
            IMSRawData.upload_id == upload_id,
            IMSRawData.year == year,
            IMSRawData.month == month,
            IMSRawData.brick.in_(bricks),
            IMSRawData.product_id.isnot(None),
            IMSRawData.sheet_type.in_(("brick_sales", "competition_box")),
        ).all()
        return upload_id, rows

    original_workbook_fallback = RepresentativeMarketService._brick_competition_rows_from_workbook

    def scoped_brick_competition_rows(self, brick_keys):
        upload_id = self._latest_upload_id(self.year, self.month)
        bricks = _assigned_brick_names(self.representative.id, self.year, self.month)
        if upload_id is None or not bricks:
            return None, []
        exact = CompetitionData.query.filter(
            CompetitionData.upload_id == upload_id,
            CompetitionData.metric_type == "UNIT",
            CompetitionData.is_subtotal.is_(False),
            CompetitionData.is_grand_total.is_(False),
            CompetitionData.subterritory.in_(bricks),
            func.upper(CompetitionData.sheet_name).like("%AYLIK%"),
            func.upper(CompetitionData.sheet_name).like("%REKABET%"),
            func.upper(CompetitionData.sheet_name).like("%KUTU%"),
        ).all()
        if not exact:
            exact = original_workbook_fallback(self, upload_id, brick_keys)
        return upload_id, exact

    RepresentativeMarketService._competition_rows = scoped_competition_rows
    RepresentativeMarketService._brick_raw_rows = scoped_brick_raw_rows
    RepresentativeMarketService._brick_competition_rows = scoped_brick_competition_rows

    def bounded_available_periods(self):
        prefix = f"{self.region_key}%"
        has_scope = exists().where(
            CompetitionData.upload_id == IMSUpload.id,
            CompetitionData.metric_type == "UNIT",
            CompetitionData.territory.like(prefix),
        )
        rows = (
            db.session.query(IMSUpload.year, IMSUpload.month)
            .filter(IMSUpload.status == "COMPLETED", has_scope)
            .distinct()
            .order_by(IMSUpload.year.desc(), IMSUpload.month.desc())
            .all()
        )
        return [
            {"year": int(year), "month": int(month), "label": f"{int(month):02d}/{int(year)}"}
            for year, month in rows
        ]

    RegionMarketService._available_periods = bounded_available_periods
