"""Single-source market authority for semantic KPI IMS workbooks.

New KPI-style IMS files contain explicit company KUTU and PAZAR controls on
NATIONAL and region subtotal rows.  Named rival columns are useful drill-down
observations but are not additive for every product, so summing detail rows can
inflate the market denominator.  This adapter persists those aggregate controls
inside the normal IMS transaction and makes all market read models use company,
market and competitor values from that one IMS source.

Legacy workbooks are untouched: the adapter activates only when product KPI
sheets expose the required aggregate controls.
"""
from __future__ import annotations

import re
from collections import defaultdict

import pandas as pd
from sqlalchemy import desc

from app.extensions import db
from app.models import CompetitionData, IMSUpload, Product
from app.services.alias_service import AliasService
from app.services.kpi_workbook_compat import is_product_kpi_sheet


AUTHORITY_PREFIX = "KPI MARKET AUTHORITY|"
_UNIT = "UNIT"


def _norm(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return AliasService.normalize(value)


def _key(value):
    return "".join(ch for ch in _norm(value) if ch.isalnum())


def _number(value):
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(parsed) else float(parsed)


def _sheet_product(sheet_name):
    normalized = _norm(sheet_name)
    match = re.match(r"^2 KUTU (.+) KPI$", normalized)
    return match.group(1).strip() if match else ""


def _resolve_product(label):
    match = AliasService.find_product(label)
    if match.get("matched"):
        return match.get("object")
    label_key = _key(label)
    for product in Product.query.filter(Product.is_active.is_(True)).all():
        aliases = {
            _key(product.product_name),
            _key(product.product_code),
            _key(getattr(product, "ims_name", None)),
        } - {""}
        if any(alias == label_key or alias in label_key or label_key in alias for alias in aliases):
            return product
    return None


def extract_market_authority(workbook):
    """Extract exact NATIONAL/region company+PAZAR controls from KPI sheets.

    Returns ``None`` for legacy workbooks.  KPI workbooks fail closed when an
    aggregate control is ambiguous/incomplete; guessing a denominator is never
    allowed.
    """
    kpi_sheets = [(name, frame) for name, frame in (workbook or {}).items() if is_product_kpi_sheet(name)]
    if not kpi_sheets:
        return None

    extracted = {}
    expected_locations = None
    for sheet_name, frame in kpi_sheets:
        product_label = _sheet_product(sheet_name)
        product = _resolve_product(product_label)
        if product is None:
            raise ValueError(f"KPI pazar otoritesi ürün eşleşmesi bulunamadı: {sheet_name}")

        header = next(
            (
                row
                for row in range(min(20, len(frame)))
                if any(_norm(value) == "PAZAR" for value in frame.iloc[row].tolist())
            ),
            None,
        )
        if header is None:
            raise ValueError(f"KPI pazar otoritesi PAZAR başlığı bulunamadı: {sheet_name}")

        labels = [_norm(value) for value in frame.iloc[header].tolist()]
        product_aliases = {
            _key(product.product_name),
            _key(product.product_code),
            _key(getattr(product, "ims_name", None)),
            _key(product_label),
        } - {""}
        own_columns = [
            index for index, label in enumerate(labels)
            if _key(label) and any(
                _key(label) == alias or _key(label).startswith(alias)
                for alias in product_aliases
            )
        ]
        pazar_columns = [index for index, label in enumerate(labels) if label == "PAZAR"]
        if len(own_columns) != 1 or len(pazar_columns) != 1:
            raise ValueError(
                f"KPI pazar otoritesi kolonları belirsiz: {sheet_name} "
                f"own={own_columns} pazar={pazar_columns}"
            )

        controls = {}
        for source_index in range(header + 1, len(frame)):
            row = frame.iloc[source_index]
            territory = _norm(row.iloc[0]) if frame.shape[1] > 0 else ""
            province = _norm(row.iloc[1]) if frame.shape[1] > 1 else ""
            brick = _norm(row.iloc[2]) if frame.shape[1] > 2 else ""
            if brick == "NATIONAL":
                location = "NATIONAL"
            elif "SUBTOTAL" in province or "SUBTOTAL" in brick:
                candidate = territory or brick
                location = candidate if re.match(r"^\d{3}(?:\s|$)", candidate) else ""
            else:
                continue
            if not location:
                continue

            own = _number(row.iloc[own_columns[0]])
            market = _number(row.iloc[pazar_columns[0]])
            if own is None or market is None:
                raise ValueError(
                    f"KPI pazar otoritesi sayısal kontrol eksik: {sheet_name} row={source_index + 1}"
                )
            if market < 0:
                raise ValueError(
                    f"KPI pazar otoritesi PAZAR negatif: {sheet_name} {location}={market}"
                )
            if own > market + 1e-9:
                raise ValueError(
                    f"KPI pazar otoritesi şirket KUTU PAZAR'dan büyük: "
                    f"{sheet_name} {location} own={own} market={market}"
                )
            if location in controls:
                raise ValueError(f"KPI pazar otoritesi tekrar eden aggregate: {sheet_name} {location}")
            controls[location] = {
                "company": own,
                "market": market,
                "source_row": int(source_index + 1),
            }

        if "NATIONAL" not in controls:
            raise ValueError(f"KPI pazar otoritesi NATIONAL satırı yok: {sheet_name}")
        locations = frozenset(controls)
        if expected_locations is None:
            expected_locations = locations
        elif locations != expected_locations:
            raise ValueError(
                f"KPI pazar aggregate kapsamı ürünler arasında farklı: {sheet_name} "
                f"expected={sorted(expected_locations)} actual={sorted(locations)}"
            )
        extracted[int(product.id)] = {
            "product_name": product.product_name,
            "sheet_name": sheet_name,
            "controls": controls,
        }

    if not extracted:
        return None
    active_ids = {int(product.id) for product in Product.query.filter(Product.is_active.is_(True)).all()}
    if active_ids and set(extracted) != active_ids:
        raise ValueError(
            "KPI pazar ürün kapsamı aktif ürünlerle eşleşmiyor: "
            f"source={sorted(extracted)} active={sorted(active_ids)}"
        )
    return extracted


def persist_market_authority(service, year, month, week_number=None):
    extracted = extract_market_authority(service.workbook)
    if not extracted:
        return 0
    upload_id = int(service.upload.id)
    CompetitionData.query.filter(
        CompetitionData.upload_id == upload_id,
        CompetitionData.sheet_name.like(f"{AUTHORITY_PREFIX}%"),
    ).delete(synchronize_session=False)

    mappings = []
    for product in extracted.values():
        group = str(product["product_name"])
        sheet_name = f"{AUTHORITY_PREFIX}{_norm(group)}"
        for location, control in product["controls"].items():
            common = {
                "upload_id": upload_id,
                "sheet_name": sheet_name,
                "period_type": "MONTHLY",
                "year": int(year),
                "month": int(month),
                "week_number": int(week_number) if week_number is not None else None,
                "territory": location,
                "subterritory": location,
                "product_group": group,
                "metric_type": _UNIT,
                "source_row": int(control["source_row"]),
                "is_grand_total": False,
            }
            mappings.append({
                **common,
                "product_name": group,
                "metric_value": float(control["company"]),
                "is_company_product": True,
                "is_competitor": False,
                "is_subtotal": False,
            })
            mappings.append({
                **common,
                "product_name": f"{group} PAZAR",
                "metric_value": float(control["market"]),
                "is_company_product": False,
                "is_competitor": False,
                "is_subtotal": True,
            })
    if mappings:
        db.session.bulk_insert_mappings(CompetitionData, mappings)
        db.session.flush()
    service.statistics["kpi_market_authority_rows"] = len(mappings)
    service.statistics["competition_records"] = int(service.statistics.get("competition_records", 0) or 0) + len(mappings)
    return len(mappings)


def _latest_authority_upload(year, month):
    return (
        db.session.query(IMSUpload)
        .join(CompetitionData, CompetitionData.upload_id == IMSUpload.id)
        .filter(
            IMSUpload.year == int(year),
            IMSUpload.month == int(month),
            IMSUpload.status == "COMPLETED",
            CompetitionData.sheet_name.like(f"{AUTHORITY_PREFIX}%"),
            CompetitionData.metric_type == _UNIT,
        )
        .order_by(desc(IMSUpload.week_number), desc(IMSUpload.completed_at), desc(IMSUpload.id))
        .first()
    )


def _authority(upload_id, territory):
    rows = CompetitionData.query.filter(
        CompetitionData.upload_id == int(upload_id),
        CompetitionData.sheet_name.like(f"{AUTHORITY_PREFIX}%"),
        CompetitionData.metric_type == _UNIT,
        CompetitionData.territory == str(territory),
    ).all()
    buckets = defaultdict(dict)
    for row in rows:
        product_key = _key(row.product_group)
        if not product_key:
            continue
        if row.is_subtotal:
            buckets[product_key]["market"] = float(row.metric_value or 0.0)
        elif row.is_company_product:
            buckets[product_key]["company"] = float(row.metric_value or 0.0)
            buckets[product_key]["product_name"] = str(row.product_group)
    return {
        product_key: values
        for product_key, values in buckets.items()
        if "company" in values and "market" in values
    }


def _find_control(controls, product_name):
    product_key = _key(product_name)
    exact = controls.get(product_key)
    if exact is not None:
        return exact
    return next(
        (values for key, values in controls.items() if key in product_key or product_key in key),
        None,
    )


def normalize_national_payload(payload, controls):
    if not controls:
        return payload
    groups = payload.get("groups") or []
    for row in groups:
        control = _find_control(controls, row.get("company_product"))
        if control is None:
            raise RuntimeError(f"NATIONAL KPI market control missing: {row.get('company_product')}")
        company = float(control["company"])
        market = float(control["market"])
        competitor = market - company
        row.update({
            "metric_mode": _UNIT,
            "company_value": round(company, 2),
            "market_value": round(market, 2),
            "competitor_value": round(competitor, 2),
            "company_sales_unit": round(company, 2),
            "market_sales_unit": round(market, 2),
            "competitor_sales_unit": round(competitor, 2),
            "company_share_percent": round(company * 100.0 / market, 2) if market else 0.0,
            "market_available": True,
            "data_status": "KPI PAZAR + IMS KUTU",
        })
    company_total = sum(float(row.get("company_value") or 0.0) for row in groups)
    market_total = sum(float(row.get("market_value") or 0.0) for row in groups)
    competitor_total = market_total - company_total
    payload.update({
        "has_competition": bool(groups),
        "metric_mode": _UNIT,
        "metric_label": "Kutu",
        "metric_suffix": "kutu",
        "company_total_value": round(company_total, 2),
        "market_total_value": round(market_total, 2),
        "competitor_total_value": round(competitor_total, 2),
        "market_total_unit": round(market_total, 2),
        "company_total_unit": round(company_total, 2),
        "competitor_total_unit": round(competitor_total, 2),
        "company_share_percent": round(company_total * 100.0 / market_total, 2) if market_total else 0.0,
    })
    return payload


def normalize_region_payload(payload, controls, display_integer=None):
    if not controls:
        return payload
    rows = payload.get("rows") or []
    display_integer = display_integer or (lambda value: round(value))
    for row in rows:
        control = _find_control(controls, row.get("product_name"))
        if control is None:
            raise RuntimeError(f"Region KPI market control missing: {row.get('product_name')}")
        company = float(control["company"])
        market = float(control["market"])
        competitor = market - company
        precise = company * 100.0 / market if market else 0.0
        target = float(row.get("target_unit") or 0.0)
        row.update({
            "company_unit": round(company, 2),
            "market_company_unit": round(company, 2),
            "competitor_unit": round(competitor, 2),
            "market_unit": round(market, 2),
            "share_percent": display_integer(precise),
            "precise_share_percent": round(precise, 6),
            "market_share_source": "IMS_KPI_AGGREGATE_PAZAR",
            "realization_percent": round(company * 100.0 / target, 1) if target else 0.0,
            "attention": "strong" if precise >= 50 else "warning" if precise >= 30 else "critical",
        })
    company_total = sum(float(row.get("company_unit") or 0.0) for row in rows)
    market_total = sum(float(row.get("market_unit") or 0.0) for row in rows)
    competitor_total = market_total - company_total
    precise_total = company_total * 100.0 / market_total if market_total else 0.0
    payload["source"] = "IMS_KPI_AGGREGATE"
    payload["market_share_source"] = "IMS_KPI_AGGREGATE_PAZAR"
    payload["has_data"] = any(float(row.get("market_unit") or 0.0) > 0 for row in rows)
    payload["totals"] = {
        "company_unit": round(company_total, 2),
        "effective_company_unit": round(company_total, 2),
        "competitor_unit": round(competitor_total, 2),
        "market_unit": round(market_total, 2),
        "share_percent": display_integer(precise_total),
        "precise_share_percent": round(precise_total, 6),
    }
    return payload


def normalize_representative_payload(payload):
    """Keep rep market cards on the same KPI brick source as their denominator."""
    brick_rows = payload.get("brick_product_rows") or []
    if not brick_rows:
        return payload
    source = defaultdict(lambda: {"company": 0.0, "market": 0.0})
    for row in brick_rows:
        key = _key(row.get("product_name"))
        source[key]["company"] += float(row.get("company_unit") or 0.0)
        source[key]["market"] += float(row.get("market_unit") or 0.0)
    rows = payload.get("rows") or []
    for row in rows:
        product = row.get("product")
        product_name = getattr(product, "product_name", "")
        values = source.get(_key(product_name))
        if not values:
            continue
        company = values["company"]
        market = values["market"]
        competitor = market - company
        target = float(row.get("target_unit") or 0.0)
        row.update({
            "actual_unit": round(company, 2),
            "market_unit": round(market, 2),
            "competitor_unit": round(competitor, 2),
            "share_percent": round(company * 100.0 / market, 1) if market else 0.0,
            "gap_unit": round(competitor - company, 2),
            "realization_percent": round(company * 100.0 / target, 1) if target else 0.0,
            "realization_source": "IMS_KPI",
        })
    payload["chart_rows"] = [
        {
            "product_name": getattr(row.get("product"), "product_name", ""),
            "actual_unit": float(row.get("actual_unit") or 0.0),
            "competitor_unit": float(row.get("competitor_unit") or 0.0),
        }
        for row in rows
    ]
    company_total = sum(float(row.get("actual_unit") or 0.0) for row in rows)
    market_total = sum(float(row.get("market_unit") or 0.0) for row in rows)
    competitor_total = market_total - company_total
    payload["totals"] = {
        "actual_unit": round(company_total, 2),
        "market_unit": round(market_total, 2),
        "competitor_unit": round(competitor_total, 2),
        "share_percent": round(company_total * 100.0 / market_total, 1) if market_total else 0.0,
    }
    return payload


def install_kpi_market_import_authority():
    from app.services.ims_import_service import IMSImportService
    if getattr(IMSImportService, "_kpi_market_import_authority_installed", False):
        return
    original = IMSImportService.process_workbook

    def process_with_market_authority(self, year, month, week_number=None):
        result = original(self, year, month, week_number=week_number)
        if self._is_current_week_snapshot(year, month, week_number):
            persist_market_authority(self, year, month, week_number=week_number)
        return result

    IMSImportService.process_workbook = process_with_market_authority
    IMSImportService._kpi_market_import_authority_installed = True


def install_kpi_market_read_authority():
    from app.services.market_analysis_service import MarketAnalysisService
    from app.services.region_market_service import RegionMarketService
    from app.services.representative_market_service import RepresentativeMarketService

    if not getattr(MarketAnalysisService, "_kpi_market_read_authority_installed", False):
        original_market = MarketAnalysisService.build

        def national_build(self):
            payload = original_market(self)
            upload = _latest_authority_upload(self.year, self.month)
            if upload is None or int(upload.id) != int(payload.get("upload_id") or upload.id):
                # MarketAnalysisService historically does not expose upload_id;
                # latest authority is safe only for the current completed period.
                pass
            if upload is not None and int(upload.week_number or 0) == int(payload.get("latest_week") or upload.week_number or 0):
                controls = _authority(upload.id, "NATIONAL")
                normalize_national_payload(payload, controls)
                payload["source_week"] = int(upload.week_number) if upload.week_number is not None else payload.get("source_week")
                payload["source_state"] = MarketAnalysisService.SOURCE_CURRENT
                payload["is_current"] = True
                payload["is_fallback"] = False
                payload["source_file"] = upload.file_name
                payload["source_message"] = (
                    f"Veriler güncel {upload.week_number}. hafta IMS dosyasının aynı kaynak KPI KUTU/PAZAR kontrollerinden alınmıştır."
                )
            return payload

        MarketAnalysisService._kpi_market_read_original_build = original_market
        MarketAnalysisService.build = national_build
        MarketAnalysisService._kpi_market_read_authority_installed = True

    if not getattr(RegionMarketService, "_kpi_market_read_authority_installed", False):
        original_region = RegionMarketService.build

        def region_build(self):
            payload = original_region(self)
            upload = _latest_authority_upload(self.year, self.month)
            if upload is None:
                return payload
            controls = _authority(upload.id, self.region_key)
            if controls:
                normalize_region_payload(payload, controls, self._display_integer)
                payload["upload_id"] = int(upload.id)
            return payload

        RegionMarketService._kpi_market_read_original_build = original_region
        RegionMarketService.build = region_build
        RegionMarketService._kpi_market_read_authority_installed = True

    if not getattr(RepresentativeMarketService, "_kpi_market_read_authority_installed", False):
        original_rep = RepresentativeMarketService.build

        def representative_build(self):
            payload = original_rep(self)
            upload = _latest_authority_upload(self.year, self.month)
            if upload is not None and int(payload.get("upload_id") or 0) == int(upload.id):
                normalize_representative_payload(payload)
            return payload

        RepresentativeMarketService._kpi_market_read_original_build = original_rep
        RepresentativeMarketService.build = representative_build
        RepresentativeMarketService._kpi_market_read_authority_installed = True
