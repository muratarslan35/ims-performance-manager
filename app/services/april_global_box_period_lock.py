"""Global April+ TL-to-box read contract with production-period locking.

Rules:
- April 2026+ open IMS periods calculate company target/actual boxes from
  authoritative TL / product unit price everywhere that still exposes an
  independent national/region-market box path.
- Once an applied production result exists for a period, that period is closed:
  the stored P2/P1 production values remain authoritative and this adapter does
  not recalculate historical boxes.
- IMS/target imports are rejected for closed production periods so a later
  upload cannot silently rewrite the source tables behind a closed month.
"""

from decimal import Decimal

from app.extensions import db
from app.models import Product
from app.services.production_result_service import ProductionResultService
from app.services.tl_box_calculation_service import TLBoxCalculationService


def is_production_locked(year, month):
    """A period closes as soon as an accepted P1/P2 production result exists."""
    return ProductionResultService.final_upload(int(year), int(month)) is not None


def _open_april_period(year, month):
    return TLBoxCalculationService.applies(int(year), int(month)) and not is_production_locked(year, month)


def _prices(product_ids):
    ids = sorted({int(item) for item in product_ids if item is not None})
    if not ids:
        return {}
    return {
        int(product_id): unit_price
        for product_id, unit_price in db.session.query(Product.id, Product.unit_price).filter(Product.id.in_(ids)).all()
    }


def _recalculate_national_payload(payload, year, month):
    """Align NATIONAL box target/actual with the same TL formula as rep/region."""
    if not payload or not _open_april_period(year, month):
        return payload
    products = list(payload.get("products") or [])
    prices = _prices(item.get("product_id") for item in products)
    for item in products:
        product_id = int(item.get("product_id") or 0)
        price = prices.get(product_id)
        target_unit = TLBoxCalculationService.boxes_from_tl(item.get("target_tl") or 0, price)
        actual_unit = TLBoxCalculationService.boxes_from_tl(item.get("actual_tl") or 0, price)
        item["unit_target"] = float(target_unit)
        item["unit_actual"] = float(actual_unit)
        item["unit_realization_percent"] = (
            round(float(actual_unit * Decimal("100") / target_unit), 1) if target_unit else 0.0
        )
    target = sum(Decimal(str(item.get("unit_target") or 0)) for item in products)
    actual = sum(Decimal(str(item.get("unit_actual") or 0)) for item in products)
    payload["unit_target"] = float(target)
    payload["unit_actual"] = float(actual)
    payload["unit_realization_percent"] = round(float(actual * Decimal("100") / target), 2) if target else 0.0
    payload["box_source"] = "IMS_TL_DIV_UNIT_PRICE"
    return payload


def _region_effective_units(service, rows):
    """Aggregate the already-canonical representative read path for a region."""
    product_ids = {int(row.get("product_id")) for row in rows if row.get("product_id") is not None}
    totals = {product_id: [Decimal("0"), Decimal("0")] for product_id in product_ids}
    for representative_id in service.representative_ids:
        effective = ProductionResultService.effective_products(
            service.year, service.month, representative_id, product_ids
        )
        for product_id, values in effective.items():
            if product_id not in totals:
                continue
            totals[product_id][0] += Decimal(str(values.get("target_unit") or 0))
            totals[product_id][1] += Decimal(str(values.get("actual_unit") or 0))
    return totals


def _recalculate_region_market_payload(service, payload):
    """Keep competitor market units intact; align only company target/actual boxes."""
    if not payload or not _open_april_period(service.year, service.month):
        return payload
    rows = list(payload.get("rows") or [])
    effective = _region_effective_units(service, rows)
    for row in rows:
        product_id = int(row.get("product_id") or 0)
        target_unit, company_unit = effective.get(product_id, (Decimal("0"), Decimal("0")))
        row["target_unit"] = float(target_unit)
        row["company_unit"] = float(company_unit)
        row["realization_percent"] = (
            round(float(company_unit * Decimal("100") / target_unit), 1) if target_unit else 0.0
        )
    totals = payload.get("totals") or {}
    totals["effective_company_unit"] = round(sum(float(row.get("company_unit") or 0) for row in rows), 2)
    payload["totals"] = totals
    payload["company_box_source"] = "IMS_TL_DIV_UNIT_PRICE"
    return payload


def install_april_global_box_period_lock():
    """Install once after existing read/import adapters have been registered."""
    from app.query.dashboard_query import DashboardQuery
    from app.services.ims_import_service import IMSImportService
    from app.services.region_market_service import RegionMarketService
    from app.services.target_import_service import TargetImportService

    if getattr(DashboardQuery, "_april_global_box_period_lock_installed", False):
        return

    original_national = DashboardQuery.load_national_dashboard_metrics

    def locked_national(self, filters=None):
        payload = original_national(self, filters)
        if not filters or filters.year is None or filters.month is None:
            return payload
        return _recalculate_national_payload(payload, filters.year, filters.month)

    original_region_build = RegionMarketService._build

    def locked_region_build(self, upload_id, production_upload_id):
        payload = original_region_build(self, upload_id, production_upload_id)
        return _recalculate_region_market_payload(self, payload)

    original_ims_run = IMSImportService.run

    def locked_ims_run(self, year, month, *args, **kwargs):
        if is_production_locked(year, month):
            raise ValueError(
                f"{int(month):02d}/{int(year)} üretim sonucu ile kapatıldı; kapalı döneme IMS yüklenemez."
            )
        return original_ims_run(self, year, month, *args, **kwargs)

    original_target_run = TargetImportService.run

    def locked_target_run(self, year, month, *args, **kwargs):
        if is_production_locked(year, month):
            raise ValueError(
                f"{int(month):02d}/{int(year)} üretim sonucu ile kapatıldı; kapalı dönem hedefleri değiştirilemez."
            )
        return original_target_run(self, year, month, *args, **kwargs)

    DashboardQuery.load_national_dashboard_metrics = locked_national
    RegionMarketService._build = locked_region_build
    IMSImportService.run = locked_ims_run
    TargetImportService.run = locked_target_run
    DashboardQuery._april_global_box_period_lock_installed = True
