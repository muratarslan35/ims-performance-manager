from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
from threading import Lock
import time

from flask import current_app

from sqlalchemy import and_, func, or_

from app.extensions import db
from app.models import (
    IMSSummary,
    ProductionNationalProductResult,
    ProductionRegionProductResult,
    ProductionResult,
    ProductionResultUpload,
    Target,
    Product,
)
from app.services.alias_service import AliasService
from app.services.product_unit_price_service import ProductUnitPriceService
from app.services.tl_box_calculation_service import TLBoxCalculationService


class ProductionResultService:
    """Single source of truth for accepted period realizations.

    Priority is evaluated per representative/product with no waiting state:
    production 2 > production 1 > IMS. Production percentages are final, may
    exceed 100, and exact stored TL/unit targets are never rounded or rebuilt.
    """

    _effective_batch_override = ContextVar("production_effective_batch_override", default=None)
    _quota_cache = {}
    _quota_cache_lock = Lock()
    _quota_cache_seconds = 60

    @staticmethod
    def _d(value):
        return Decimal(str(value or 0))

    @classmethod
    def applied_uploads(cls, year, month):
        return (
            ProductionResultUpload.query.filter_by(
                year=year, month=month, status=ProductionResultUpload.STATUS_APPLIED,
            )
            .order_by(
                ProductionResultUpload.production_stage.desc(),
                ProductionResultUpload.applied_at.desc(),
                ProductionResultUpload.id.desc(),
            )
            .all()
        )

    @classmethod
    def final_upload(cls, year, month):
        uploads = cls.applied_uploads(year, month)
        return uploads[0] if uploads else None

    @classmethod
    def quota_product_months(cls, months):
        """Reuse nationwide approval briefly within a web worker's read path."""
        periods = tuple(sorted({(int(year), int(month)) for year, month in months}))
        if not periods:
            return {}
        if current_app.testing:
            return cls._quota_product_months_uncached(periods)
        database = str(current_app.config.get("SQLALCHEMY_DATABASE_URI") or "")
        now = time.monotonic()
        with cls._quota_cache_lock:
            cached = {
                period: cls._quota_cache.get((database, period))
                for period in periods
            }
        missing = [
            period for period, entry in cached.items()
            if entry is None or now - entry[0] >= cls._quota_cache_seconds
        ]
        if missing:
            fresh = cls._quota_product_months_uncached(missing)
            with cls._quota_cache_lock:
                for period in missing:
                    products = {
                        int(product_id) for product_id, detected in fresh.items()
                        if period in detected
                    }
                    cls._quota_cache[(database, period)] = (time.monotonic(), products)
                cached = {
                    period: cls._quota_cache[(database, period)]
                    for period in periods
                }
        result = {}
        for period in periods:
            for product_id in cached[period][1]:
                result.setdefault(product_id, []).append(period)
        return result

    @classmethod
    def _quota_product_months_uncached(cls, months):
        """Detect stock-quota exemptions from official production results."""
        periods = tuple(sorted({(int(year), int(month)) for year, month in months}))
        uploads = {(year, month): cls.final_upload(year, month) for year, month in periods}
        selected = {period: upload for period, upload in uploads.items() if upload is not None}
        if not selected:
            return {}
        rows = ProductionRegionProductResult.query.filter(
            ProductionRegionProductResult.upload_id.in_([upload.id for upload in selected.values()])
        ).all()
        rows_by_upload = {}
        for row in rows:
            rows_by_upload.setdefault(int(row.upload_id), []).append(row)

        # A product with an IMS quota but no positive sale anywhere in Türkiye
        # and no active product line in the final production workbook is a
        # stock quota exit. This applies to existing P2 uploads without
        # renaming or reimporting the workbook.
        period_filter = or_(*[
            and_(Target.year == year, Target.month == month)
            for year, month in periods
        ])
        ims_filter = or_(*[
            and_(IMSSummary.year == year, IMSSummary.month == month)
            for year, month in periods
        ])
        target_amounts = {
            (int(year), int(month), int(product_id)): amount
            for year, month, product_id, amount in db.session.query(
                Target.year, Target.month, Target.product_id, func.sum(Target.tl_target)
            ).filter(period_filter).group_by(
                Target.year, Target.month, Target.product_id
            ).all()
        }
        ims_sales = {
            (int(year), int(month), int(product_id)): (tl, unit)
            for year, month, product_id, tl, unit in db.session.query(
                IMSSummary.year, IMSSummary.month, IMSSummary.product_id,
                func.max(IMSSummary.tl), func.max(IMSSummary.unit),
            ).filter(ims_filter).group_by(
                IMSSummary.year, IMSSummary.month, IMSSummary.product_id
            ).all()
        }
        selected_ids = [int(upload.id) for upload in selected.values()]
        production = {
            (int(upload_id), int(product_id)): (actual, unit)
            for upload_id, product_id, actual, unit in db.session.query(
                ProductionResult.upload_id, ProductionResult.product_id,
                func.max(ProductionResult.actual_tl), func.max(ProductionResult.actual_unit),
            ).filter(ProductionResult.upload_id.in_(selected_ids)).group_by(
                ProductionResult.upload_id, ProductionResult.product_id
            ).all()
        }
        national = {
            (int(row.upload_id), int(row.product_id)): row
            for row in ProductionNationalProductResult.query.filter(
                ProductionNationalProductResult.upload_id.in_(selected_ids)
            ).all()
        }
        empty_by_period = {}
        for period, upload in selected.items():
            year, month = period
            empty_by_period[period] = {
                product_id for (target_year, target_month, product_id), target
                in target_amounts.items()
                if (target_year, target_month) == period
                and cls._d(target) > 0
                and all(cls._d(value) <= 0 for value in production.get((int(upload.id), product_id), (0, 0)))
                and all(cls._d(value) <= 0 for value in ims_sales.get((year, month, product_id), (0, 0)))
                and (
                    (int(upload.id), product_id) not in national
                    or (
                        cls._d(national[(int(upload.id), product_id)].actual_tl) <= 0
                        and cls._d(national[(int(upload.id), product_id)].actual_unit) <= 0
                    )
                )
                and all(
                    cls._d(row.actual_tl) <= 0 and cls._d(row.actual_unit) <= 0
                    for row in rows_by_upload.get(int(upload.id), [])
                    if row.product_id == product_id
                )
            }

        result = {}
        tolerance = Decimal("0.05")
        for period, upload in selected.items():
            upload_rows = rows_by_upload.get(int(upload.id), [])
            expected_regions = {str(row.region_code) for row in upload_rows}
            by_product = {}
            for row in upload_rows:
                by_product.setdefault(int(row.product_id), []).append(row)
            for product_id in set(by_product) | empty_by_period[period]:
                if product_id in empty_by_period[period]:
                    result.setdefault(product_id, []).append(period)
                    continue
                product_rows = by_product[product_id]
                product_regions = {str(row.region_code) for row in product_rows}
                if not expected_regions or product_regions != expected_regions:
                    continue
                source = AliasService.normalize(" ".join(filter(None, (upload.file_name, upload.stored_file_name))))
                marker = next((item for item in ("KOTA SATIS", "KOTA CIKIS") if item in source), None)
                if marker is None:
                    continue
                quota_names = f" {source.split(marker, 1)[1]} "
                product = product_rows[0].product
                labels = {
                    AliasService.normalize(value)
                    for value in (product.product_name, product.product_code, product.ims_name)
                    if value
                }
                if not any(f" {label} " in quota_names for label in labels if label):
                    continue
                if all(
                    cls._d(row.realization_percent) >= Decimal("100") - tolerance
                    and cls._d(row.actual_tl) >= cls._d(row.target_tl) - tolerance
                    for row in product_rows
                ):
                    result.setdefault(product_id, []).append(period)
        return result

    @classmethod
    def final_product_result(cls, year, month, representative_id, product_id):
        for upload in cls.applied_uploads(year, month):
            result = ProductionResult.query.filter_by(
                upload_id=upload.id, representative_id=representative_id, product_id=product_id,
            ).first()
            if result is not None:
                return result
        return None

    @classmethod
    def effective_products(cls, year, month, representative_id, product_ids=None):
        """Resolve a whole representative period in a bounded query set."""
        year, month, representative_id = int(year), int(month), int(representative_id)
        product_filter = {int(item) for item in product_ids or ()}

        period_price = ProductUnitPriceService.period_price_expression(year, month)
        target_query = db.session.query(Target, period_price).join(
            Product, Product.id == Target.product_id
        ).filter(
            Target.year == year,
            Target.month == month,
            Target.representative_id == representative_id,
        )
        if product_filter:
            target_query = target_query.filter(Target.product_id.in_(product_filter))
        target_pairs = target_query.all()
        targets = [row[0] for row in target_pairs]
        targets_by_product = {int(target.product_id): target for target in targets}
        product_prices = {int(target.product_id): price for target, price in target_pairs}
        resolved_ids = product_filter or set(targets_by_product)
        if not resolved_ids:
            return {}

        summary_query = IMSSummary.query.filter_by(
            year=year, month=month, representative_id=representative_id,
        ).filter(IMSSummary.product_id.in_(resolved_ids))
        summaries = summary_query.all()
        summaries_by_product = {int(summary.product_id): summary for summary in summaries}

        uploads = cls.applied_uploads(year, month)
        upload_ids = [int(upload.id) for upload in uploads]
        production_by_key = {}
        if upload_ids:
            rows = ProductionResult.query.filter(
                ProductionResult.upload_id.in_(upload_ids),
                ProductionResult.representative_id == representative_id,
                ProductionResult.product_id.in_(resolved_ids),
            ).all()
            production_by_key = {(int(row.upload_id), int(row.product_id)): row for row in rows}

        resolved = {}
        for product_id in resolved_ids:
            target = targets_by_product.get(product_id)
            target_tl = cls._d(target.tl_target if target else 0)
            target_unit = cls._d(target.unit_target if target else 0)
            selected_upload = None
            selected_result = None
            for upload in uploads:
                selected_result = production_by_key.get((int(upload.id), product_id))
                if selected_result is not None:
                    selected_upload = upload
                    break

            if selected_result is not None:
                # A finalized production workbook is authoritative for both
                # targets and actuals. Keep IMS Target rows only as a fallback
                # for older production uploads that did not persist target
                # columns. This also makes P2 replace P1/IMS completely.
                production_target_tl = (
                    cls._d(selected_result.target_tl)
                    if selected_result.target_tl is not None
                    else target_tl
                )
                production_target_unit = (
                    cls._d(selected_result.target_unit)
                    if selected_result.target_unit is not None
                    else target_unit
                )
                percent = (
                    cls._d(selected_result.actual_tl) * Decimal("100") / production_target_tl
                    if production_target_tl and selected_result.actual_tl is not None
                    else cls._d(selected_result.realization_percent)
                )
                actual_tl = (
                    cls._d(selected_result.actual_tl)
                    if selected_result.actual_tl is not None
                    else production_target_tl * percent / Decimal("100")
                )
                actual_unit = (
                    cls._d(selected_result.actual_unit)
                    if selected_result.actual_unit is not None
                    else production_target_unit * percent / Decimal("100")
                )
                resolved[product_id] = {
                    "source": f"PRODUCTION_{selected_upload.production_stage}",
                    "complete": True,
                    "target_tl": production_target_tl,
                    "target_unit": production_target_unit,
                    "realization_percent": percent,
                    "actual_tl": actual_tl,
                    "actual_unit": actual_unit,
                }
                continue

            summary = summaries_by_product.get(product_id)
            actual_tl = cls._d(summary.tl if summary else 0)
            if TLBoxCalculationService.applies(year, month):
                target_unit = TLBoxCalculationService.boxes_from_tl(target_tl, product_prices.get(product_id))
                actual_unit = TLBoxCalculationService.boxes_from_tl(actual_tl, product_prices.get(product_id))
            else:
                actual_unit = cls._d(summary.unit if summary else 0)
            percent = (actual_tl / target_tl * Decimal("100")) if target_tl else Decimal("0")
            resolved[product_id] = {
                "source": "IMS",
                "complete": summary is not None,
                "target_tl": target_tl,
                "target_unit": target_unit,
                "realization_percent": percent,
                "actual_tl": actual_tl,
                "actual_unit": actual_unit,
            }
        return resolved

    @classmethod
    @contextmanager
    def use_effective_batch(cls, year, month, representative_id, rows):
        payload = {"key": (int(year), int(month), int(representative_id)), "rows": rows}
        token = cls._effective_batch_override.set(payload)
        try:
            yield rows
        finally:
            cls._effective_batch_override.reset(token)

    @classmethod
    def effective_product(cls, year, month, representative_id, product_id):
        override = cls._effective_batch_override.get()
        key = (int(year), int(month), int(representative_id))
        if override and override.get("key") == key:
            row = (override.get("rows") or {}).get(int(product_id))
            if row is not None:
                return row

        target = Target.query.filter_by(
            year=year, month=month, representative_id=representative_id, product_id=product_id,
        ).first()
        target_tl = cls._d(target.tl_target if target else 0)
        target_unit = cls._d(target.unit_target if target else 0)

        for upload in cls.applied_uploads(year, month):
            result = ProductionResult.query.filter_by(
                upload_id=upload.id, representative_id=representative_id, product_id=product_id,
            ).first()
            if result is None:
                continue
            production_target_tl = (
                cls._d(result.target_tl)
                if result.target_tl is not None
                else target_tl
            )
            production_target_unit = (
                cls._d(result.target_unit)
                if result.target_unit is not None
                else target_unit
            )
            percent = (
                cls._d(result.actual_tl) * Decimal("100") / production_target_tl
                if production_target_tl and result.actual_tl is not None
                else cls._d(result.realization_percent)
            )
            actual_tl = (
                cls._d(result.actual_tl)
                if result.actual_tl is not None
                else production_target_tl * percent / Decimal("100")
            )
            actual_unit = (
                cls._d(result.actual_unit)
                if result.actual_unit is not None
                else production_target_unit * percent / Decimal("100")
            )
            return {
                "source": f"PRODUCTION_{upload.production_stage}",
                "complete": True,
                "target_tl": production_target_tl,
                "target_unit": production_target_unit,
                "realization_percent": percent,
                "actual_tl": actual_tl,
                "actual_unit": actual_unit,
            }

        summary = IMSSummary.query.filter_by(
            year=year, month=month, representative_id=representative_id, product_id=product_id,
        ).first()
        actual_tl = cls._d(summary.tl if summary else 0)
        if TLBoxCalculationService.applies(year, month):
            unit_price = ProductUnitPriceService.price_for_period(product_id, year, month)
            target_unit = TLBoxCalculationService.boxes_from_tl(target_tl, unit_price)
            actual_unit = TLBoxCalculationService.boxes_from_tl(actual_tl, unit_price)
        else:
            actual_unit = cls._d(summary.unit if summary else 0)
        percent = (actual_tl / target_tl * Decimal("100")) if target_tl else Decimal("0")
        return {
            "source": "IMS",
            "complete": summary is not None,
            "target_tl": target_tl,
            "target_unit": target_unit,
            "realization_percent": percent,
            "actual_tl": actual_tl,
            "actual_unit": actual_unit,
        }

    @classmethod
    def effective_representative(cls, year, month, representative_id):
        targets = Target.query.filter_by(year=year, month=month, representative_id=representative_id).all()
        rows = [cls.effective_product(year, month, representative_id, target.product_id) for target in targets]
        complete = bool(rows) and all(row["complete"] for row in rows)
        total_target = sum((row["target_tl"] for row in rows), Decimal("0"))
        total_actual = sum((row["actual_tl"] for row in rows), Decimal("0"))
        return {
            "complete": complete,
            "source": cls._source_name(year, month),
            "target_tl": total_target,
            "actual_tl": total_actual,
            "realization_percent": (total_actual / total_target * Decimal("100")) if total_target else Decimal("0"),
            "products": rows,
        }

    @classmethod
    def _source_name(cls, year, month):
        upload = cls.final_upload(year, month)
        return f"PRODUCTION_{upload.production_stage}" if upload else "IMS"
